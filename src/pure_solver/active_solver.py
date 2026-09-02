"""Sparse active-set duel solver: screen a pool of executable builds cheaply, then let a two-sided double oracle
call the verified duel simulator only for the candidates it needs.

The heuristic screen makes the result provisional unless every outside candidate was screened. Exploratory;
backs the ``solve-active`` command and is not on the ranking pipeline.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from fractions import Fraction

from .accounts import AccountSearchBounds, AccountState, LevelRange, enumerate_account_states
from .candidate_reduction import (
    ReductionCandidate,
    candidate_from_combat_envelopes,
    select_diverse_seeds,
)
from .combat_envelope import AttackOption, build_combat_envelope
from .double_oracle import (
    OracleScreenEntry,
    OracleScreening,
    OracleScreenRequest,
    solve_double_oracle,
)
from .errors import SearchBudgetExceeded
from .evaluation import derived_seed
from .experience import standard_f2p_hitpoints_achievable
from .game_solver import StrategyCandidate, solve_strategy_space
from .legality import LegalityContext
from .matchups import ResourceMatchupResult
from .reporting import SolveReport
from .ruleset import Ruleset
from .solver import (
    DUEL_REQUIRED_MECHANICS,
    DuelStrategyCandidate,
    build_plan_actor,
    materialize_supported_strategy_pool,
    optimize_supported_matchup,
    supported_preflight,
)


def _seed_record(ruleset: Ruleset, strategy: DuelStrategyCandidate) -> ReductionCandidate:
    actor = build_plan_actor(ruleset, strategy.plan)
    inventory = strategy.plan.inventory
    candidate_id = strategy.candidate.descriptor.strategy_id
    options = tuple(
        AttackOption.from_attack_profile(f"weapon:{weapon_id}", profile)
        for weapon_id, profile in sorted(actor.weapons.items())
    )
    envelope = build_combat_envelope(
        candidate_id,
        "baseline_defence",
        options,
        hitpoints=strategy.plan.account.hitpoints_level,
        prayer=strategy.plan.account.prayer_level,
        distance=strategy.plan.opening_distance,
    )
    return candidate_from_combat_envelopes(
        candidate_id,
        (envelope,),
        comparison_class={
            "purpose": "seed_selection_only",
            "reserved_switch_slots": strategy.plan.kit.inventory_slots,
        },
        additional_metrics={
            "food_slots": inventory.swordfish + inventory.anchovy_pizza,
            "strength_potion_slots": inventory.strength_potion,
        },
        capabilities=(
            "switch:ko_weapon"
            if strategy.plan.kit.primary_weapon.item_id != strategy.plan.kit.ko_weapon.item_id
            else "switch:single_weapon",
        ),
    )


def _compact_features(candidate: ReductionCandidate) -> tuple[Fraction, ...]:
    metrics = {name: Fraction(value) for name, value in candidate.normalized_metrics}

    def maximum(fragment: str) -> Fraction:
        return max(
            (value for name, value in metrics.items() if fragment in name),
            default=Fraction(0),
        )

    return (
        maximum(":sustained:"),
        maximum(":ko:"),
        maximum(":fixed_stack:"),
        maximum(":max_range"),
        maximum(":hitpoints"),
        metrics.get("food_slots", Fraction(0)),
    )


def _normalised_feature_map(
    candidates: tuple[ReductionCandidate, ...],
) -> Mapping[str, tuple[Fraction, ...]]:
    raw = {candidate.candidate_id: _compact_features(candidate) for candidate in candidates}
    dimensions = len(next(iter(raw.values())))
    bounds = tuple(
        (
            min(values[index] for values in raw.values()),
            max(values[index] for values in raw.values()),
        )
        for index in range(dimensions)
    )
    return {
        candidate_id: tuple(
            Fraction(1) if upper == lower else (value - lower) / (upper - lower)
            for value, (lower, upper) in zip(values, bounds)
        )
        for candidate_id, values in raw.items()
    }


def _screen_from_equilibrium_features(
    features: Mapping[str, tuple[Fraction, ...]],
    *,
    outside_batch_size: int,
):
    def heuristic(attacker_id: str, defender_id: str) -> Fraction:
        attacker = features[attacker_id]
        defender = features[defender_id]
        offence_a, burst_a, stack_a, range_a, hp_a, food_a = attacker
        offence_d, burst_d, stack_d, range_d, hp_d, food_d = defender
        return (
            2 * (offence_a * (1 - hp_d) - offence_d * (1 - hp_a))
            + 2 * (burst_a * (1 - food_d) - burst_d * (1 - food_a))
            + (stack_a * (1 - hp_d) - stack_d * (1 - hp_a))
            + (range_a - range_d) / 2
        )

    def screen(request: OracleScreenRequest) -> OracleScreening:
        if request.side == "row":
            priorities = {
                candidate_id: sum(
                    (
                        weight * heuristic(candidate_id, opponent_id)
                        for opponent_id, weight in request.column_strategy
                        if weight > 0
                    ),
                    Fraction(0),
                )
                for candidate_id in request.inactive_candidates
            }
        else:
            priorities = {
                candidate_id: -sum(
                    (
                        weight * heuristic(opponent_id, candidate_id)
                        for opponent_id, weight in request.row_strategy
                        if weight > 0
                    ),
                    Fraction(0),
                )
                for candidate_id in request.inactive_candidates
            }
        ordered = sorted(
            request.inactive_candidates,
            key=lambda candidate_id: (priorities[candidate_id], candidate_id),
            reverse=True,
        )
        shortlisted = ordered[:outside_batch_size]
        return OracleScreening(
            tuple(
                OracleScreenEntry(candidate_id, priority=(priorities[candidate_id],)) for candidate_id in shortlisted
            ),
            exhaustive=len(shortlisted) == len(request.inactive_candidates),
        )

    return screen


def solve_supported_active_strategy_space(
    ruleset: Ruleset,
    *,
    attack_range: LevelRange,
    strength_range: LevelRange,
    ranged_range: LevelRange,
    prayer_range: LevelRange,
    hitpoints_range: LevelRange,
    combat_minimum: int,
    combat_maximum: int,
    samples: int,
    seed: int,
    maximum_ticks: int = 200,
    maximum_accounts: int | None = None,
    candidate_pool_size: int = 256,
    initial_active_size: int = 32,
    outside_batch_size: int = 24,
    oracle_epsilon: Fraction = Fraction(1, 50),
    oracle_max_iterations: int = 12,
    account_mode: str = "f2p_standard_training",
    allow_wiki_first: bool = False,
) -> SolveReport:
    """Run a sparse active-set search over executable builds.

    The cheap screen is intentionally heuristic and therefore produces a
    provisional result unless it happens to screen every outside candidate.
    The expensive payoff callback is the verified duel simulator wrapped in a
    pairwise restricted-grid inventory/policy search.
    """
    ruleset.preflight(DUEL_REQUIRED_MECHANICS, allow_unverified_items=allow_wiki_first)
    supported_preflight(ruleset)
    if samples < 1:
        raise ValueError("Active strategy solving requires at least one sample")
    if candidate_pool_size < 1 or initial_active_size < 1 or outside_batch_size < 1:
        raise ValueError("Candidate-pool, active-set, and outside-batch sizes must be positive")
    if oracle_epsilon < 0 or oracle_max_iterations < 1:
        raise ValueError("Oracle epsilon cannot be negative and iterations must be positive")
    if account_mode not in {"independent_hp", "f2p_standard_training"}:
        raise ValueError(f"Unknown account mode {account_mode!r}")

    enumerated = enumerate_account_states(
        AccountSearchBounds(
            attack=attack_range,
            strength=strength_range,
            ranged=ranged_range,
            magic=LevelRange(1, 1),
            prayer=prayer_range,
            hitpoints=hitpoints_range,
            combat_minimum=combat_minimum,
            combat_maximum=combat_maximum,
        ),
        ruleset.mechanics,
    )
    accounts: list[AccountState] = []
    for account in enumerated:
        if account_mode == "f2p_standard_training" and not standard_f2p_hitpoints_achievable(
            account, ruleset.mechanics
        ):
            continue
        if maximum_accounts is not None and len(accounts) >= maximum_accounts:
            raise SearchBudgetExceeded(
                f"Account search reached its explicit {maximum_accounts}-candidate budget; result is not exhaustive."
            )
        accounts.append(account)

    strategies = materialize_supported_strategy_pool(
        ruleset,
        tuple(accounts),
        maximum_strategies=candidate_pool_size,
        context=LegalityContext(allow_unverified_items=allow_wiki_first),
    )
    if not strategies:
        raise ValueError("No executable restricted-policy candidates were generated")
    by_id = {strategy.candidate.descriptor.strategy_id: strategy for strategy in strategies}
    candidate_ids = tuple(by_id)
    seed_records = tuple(_seed_record(ruleset, strategy) for strategy in strategies)
    selected = select_diverse_seeds(seed_records, min(initial_active_size, len(seed_records)))
    initial_ids = tuple(candidate.candidate_id for candidate in selected.selected_candidates)
    feature_by_id = _normalised_feature_map(seed_records)

    cache: dict[tuple[str, str], ResourceMatchupResult] = {}

    def evaluate_ids(row_id: str, column_id: str) -> ResourceMatchupResult:
        key = (row_id, column_id)
        if key not in cache:
            row = by_id[row_id]
            column = by_id[column_id]
            supported_distance = max(row.plan.opening_distance, column.plan.opening_distance)
            cache[key] = optimize_supported_matchup(
                ruleset,
                replace(row.plan, opening_distance=supported_distance),
                replace(column.plan, opening_distance=supported_distance),
                samples=samples,
                seed=derived_seed(seed, row_id, column_id),
                maximum_ticks=maximum_ticks,
            ).matchup
        return cache[key]

    def payoff(row_id: str, column_id: str) -> Fraction:
        result = evaluate_ids(row_id, column_id).matchup
        return Fraction(result.wins - result.losses, result.samples)

    oracle = solve_double_oracle(
        candidate_ids,
        payoff,
        initial_active=initial_ids,
        epsilon=oracle_epsilon,
        screen=_screen_from_equilibrium_features(feature_by_id, outside_batch_size=outside_batch_size),
        max_iterations=oracle_max_iterations,
    )
    final_active_ids = set(oracle.active_rows) | set(oracle.active_columns)
    final_ids = tuple(candidate_id for candidate_id in candidate_ids if candidate_id in final_active_ids)
    final_candidates = tuple(by_id[candidate_id].candidate for candidate_id in final_ids)

    def evaluate_candidates(row: StrategyCandidate, column: StrategyCandidate) -> ResourceMatchupResult:
        return evaluate_ids(row.descriptor.strategy_id, column.descriptor.strategy_id)

    report = solve_strategy_space(
        ruleset,
        final_candidates,
        evaluate_candidates,
        account_count=len(accounts),
        kit_count=len({by_id[candidate_id].plan.kit.canonical_id for candidate_id in final_ids}),
        inventory_count=len(final_ids),
        policy_count=len(final_ids),
        required_mechanics=DUEL_REQUIRED_MECHANICS,
    )
    verification = {
        "status": "provisional",
        "production_ready": False,
        "scope": "bounded_melee_ranged_pairwise_restricted_grid_double_oracle_v1",
        "perfect_play_claim": False,
        "magic_complete": False,
        "candidate_pool_is_bounded": True,
        "sampling_error_included_in_oracle_epsilon": False,
        "pairwise_policy_optimization": {
            "enabled": True,
            "authority": "restricted_grid_search",
            "searches": (
                "inventory",
                "eat_threshold",
                "ko_threshold",
                "food_preference",
                "repot_threshold",
            ),
        },
        "stage1_envelope": {
            "defence_states": ("baseline_defence",),
            "windows": (4, 5, 8, 12),
            "hp_thresholds": (5, 10, 15, 20, 25, 30),
            "used_for": "diverse seed selection and outside-candidate priority",
            "used_for_dominance_removal": False,
        },
        "candidate_pool_count": len(strategies),
        "initial_active_count": len(initial_ids),
        "final_active_count": len(final_ids),
        "directed_simulator_solves": len(cache),
        "directed_solves_avoided_vs_pool_all_pairs": len(strategies) ** 2 - len(cache),
        "samples_per_matchup": samples,
        "root_seed": seed,
        "oracle": oracle.to_document(),
    }
    return SolveReport(
        reproducibility_metadata=report.reproducibility_metadata,
        verification=verification,
        search=report.search,
        strategies=report.strategies,
        pairwise_matchups=report.pairwise_matchups,
        rankings=report.rankings,
        pareto_frontier=report.pareto_frontier,
        counters=report.counters,
        nash=report.nash,
        resources=report.resources,
    )
