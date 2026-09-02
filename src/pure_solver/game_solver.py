"""Final evaluation stage for a fully materialised strategy space: build the pairwise matchup matrix with the
supplied evaluator, solve the zero-sum equilibrium and assemble a ``SolveReport``. It never runs on a ruleset
that fails production preflight.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction

from .evaluation import NashEquilibrium, solve_zero_sum_hybrid
from .matchups import ResourceMatchupResult
from .reporting import (
    PairwiseMatchupReport,
    ResourceReport,
    SearchSummary,
    SolveReport,
    StrategyDescriptor,
    build_counter_summaries,
    build_nash_summary,
    build_pareto_frontier,
    build_strategy_rankings,
    merge_resource_summaries,
)
from .ruleset import Ruleset


@dataclass(frozen=True)
class StrategyCandidate:
    descriptor: StrategyDescriptor


MatchupEvaluator = Callable[[StrategyCandidate, StrategyCandidate], ResourceMatchupResult]
EquilibriumSolver = Callable[[Sequence[Sequence[int | Fraction]]], NashEquilibrium]


def solve_strategy_space(
    ruleset: Ruleset,
    strategies: Sequence[StrategyCandidate],
    evaluator: MatchupEvaluator,
    *,
    account_count: int | None = None,
    kit_count: int | None = None,
    inventory_count: int | None = None,
    policy_count: int | None = None,
    required_mechanics: tuple[str, ...] | None = None,
    equilibrium_solver: EquilibriumSolver = solve_zero_sum_hybrid,
) -> SolveReport:
    """Evaluate a fully materialized verified strategy space.

    Candidate generation is separate so exhaustive/dominance-pruned search can
    stream to durable storage. This final stage never runs on a ruleset that
    fails production preflight.
    """
    # A caller may solve a deliberately narrower, fully verified game than the
    # whole ruleset supports (for example, melee/ranged without magic).  Keep
    # the default strict production gate for the generic public entry point.
    if required_mechanics is None:
        ruleset.preflight()
    else:
        ruleset.preflight(required_mechanics)
    candidates = tuple(strategies)
    if not candidates:
        raise ValueError("Game solving requires at least one strategy")
    strategy_ids = tuple(candidate.descriptor.strategy_id for candidate in candidates)
    if len(set(strategy_ids)) != len(strategy_ids):
        raise ValueError("Strategy IDs must be unique")

    rows: list[tuple[PairwiseMatchupReport, ...]] = []
    resource_rows: dict[str, list] = {strategy_id: [] for strategy_id in strategy_ids}
    for row in candidates:
        reports: list[PairwiseMatchupReport] = []
        for column in candidates:
            evaluated = evaluator(row, column)
            reports.append(
                PairwiseMatchupReport(
                    row.descriptor.strategy_id,
                    column.descriptor.strategy_id,
                    evaluated.matchup,
                )
            )
            resource_rows[row.descriptor.strategy_id].append(evaluated.player_resources)
        rows.append(tuple(reports))
    payoff = tuple(tuple(report.payoff for report in row) for row in rows)
    equilibrium = equilibrium_solver(payoff)
    nash = build_nash_summary(strategy_ids, equilibrium)
    counters_tuple = build_counter_summaries(strategy_ids, rows)
    counters = {counter.strategy_id: counter for counter in counters_tuple}
    rankings = build_strategy_rankings(strategy_ids, rows, counters, nash.row_strategy)
    resources = tuple(
        ResourceReport(
            strategy_id,
            merge_resource_summaries(resource_rows[strategy_id]),
            len(resource_rows[strategy_id]),
        )
        for strategy_id in strategy_ids
    )
    descriptors = tuple(candidate.descriptor for candidate in candidates)
    return SolveReport(
        reproducibility_metadata=ruleset.reproducibility_metadata,
        verification={"status": "verified", "production_ready": True},
        search=SearchSummary(
            account_count=account_count
            if account_count is not None
            else len({item.account_id for item in descriptors}),
            kit_count=kit_count
            if kit_count is not None
            else len({(item.primary_weapon.get("item_id"), item.ko_weapon.get("item_id")) for item in descriptors}),
            inventory_count=inventory_count
            if inventory_count is not None
            else len(
                {
                    tuple((entry["item_id"], entry["state"], entry["quantity"]) for entry in item.inventory_entries)
                    for item in descriptors
                }
            ),
            policy_count=policy_count
            if policy_count is not None
            else len({str(sorted(item.policy.items())) for item in descriptors}),
            strategy_count=len(candidates),
            matchup_count=len(candidates) ** 2,
        ),
        strategies=descriptors,
        pairwise_matchups=tuple(report for row in rows for report in row),
        rankings=rankings,
        pareto_frontier=build_pareto_frontier(rankings),
        counters=counters_tuple,
        nash=nash,
        resources=resources,
    )
