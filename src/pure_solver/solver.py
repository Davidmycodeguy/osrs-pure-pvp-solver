"""Bounded melee/ranged duel solver: materialise executable build plans (account, kit, inventory, style),
optimise restricted policies pairwise with the duel simulator, and evaluate the strategy space into a
``SolveReport``.

Backs the exploratory ``solve`` command; the strategy budget is an explicit search scope, never a claim of
exhaustive search.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from .accounts import AccountSearchBounds, AccountState, LevelRange, enumerate_account_states
from .canonical import canonical_hash
from .consumable_dominance import prune_dominated_foods
from .duel import DuelActor, DuelRules, DuelSimulator, DuelState, RestrictedPolicy
from .errors import DataUnavailableError, SearchBudgetExceeded
from .evaluation import derived_seed
from .experience import standard_f2p_hitpoints_achievable
from .game_solver import StrategyCandidate, solve_strategy_space
from .inventory import InventoryEntry, InventoryState
from .kits import CombatKit, generate_combat_kits
from .legality import EquipmentItem, LegalityContext
from .matchups import ResourceMatchupResult, simulate_matchup_with_resources
from .mechanics import ImpactTiming
from .optimization import enumerate_restricted_policies, optimize_restricted_policy
from .profiles import (
    AttackProfile,
    MeleeProfileInput,
    RangedProfileInput,
    TargetDefence,
    VerifiedAttackTiming,
    build_melee_profile,
    build_ranged_profile,
)
from .reporting import SolveReport, StrategyDescriptor
from .ruleset import Ruleset

SUPPORTED_REQUIRED_MECHANICS = (
    "combat_level",
    "melee.effective_attack",
    "melee.attack_roll",
    "melee.effective_strength",
    "melee.max_hit",
    "melee.accuracy",
    "player.effective_defence",
    "player.defence_roll",
    "ranged.effective_attack",
    "ranged.attack_roll",
    "ranged.effective_strength",
    "ranged.max_hit",
    "ranged.rapid_attack_cooldown",
    "damage.player_successful_zero_to_one",
    "strength_potion.boost",
    "boost.combat_decay_interval_ticks",
    "potion.drink_delay_ticks",
    "potion.food_timer_independent",
    "potion.strength",
    "potion.strength_reboost_application",
    "food.swordfish",
    "food.anchovy_pizza",
)

DUEL_REQUIRED_MECHANICS = SUPPORTED_REQUIRED_MECHANICS + (
    "tick.pipeline",
    "death.simultaneous_ko",
    "melee.damage_timing",
    "ranged.projectile_timing",
)

_PLAYER_DEFENCE_PLACEHOLDER = TargetDefence(1, 0)


@dataclass(frozen=True)
class SupportedStyle:
    style_id: str
    damage_type: str
    attack_style_bonus: int
    strength_style_bonus: int
    defence_style_bonus: int


@dataclass(frozen=True)
class InventoryPlan:
    swordfish: int = 0
    anchovy_pizza: int = 0
    strength_potion: int = 0

    def build(self, *, capacity: int, reserved_switch_slots: int) -> InventoryState:
        entries = []
        if self.swordfish:
            entries.append(InventoryEntry("swordfish", "whole", self.swordfish))
        if self.anchovy_pizza:
            entries.append(InventoryEntry("anchovy_pizza", "full", self.anchovy_pizza))
        if self.strength_potion:
            entries.append(InventoryEntry("strength_potion", "4_dose", self.strength_potion))
        inventory = InventoryState(tuple(entries), capacity)
        if inventory.occupied_slots + reserved_switch_slots > capacity:
            raise DataUnavailableError(f"Inventory plan exceeds {capacity} slots once switch slots are reserved")
        return inventory


@dataclass(frozen=True)
class BuildPlan:
    account: AccountState
    kit: CombatKit
    primary_style: SupportedStyle
    ko_style: SupportedStyle
    inventory: InventoryPlan
    opening_distance: int


@dataclass(frozen=True)
class PolicySearchResult:
    policy: RestrictedPolicy
    objective: float
    iterations: int


@dataclass(frozen=True)
class SupportedMatchupResult:
    player_policy: PolicySearchResult
    opponent_policy: PolicySearchResult
    matchup: ResourceMatchupResult


@dataclass(frozen=True)
class DuelStrategyCandidate:
    """A reportable strategy paired with the executable duel inputs behind it."""

    candidate: StrategyCandidate
    plan: BuildPlan
    policy: RestrictedPolicy


def _policy_document(policy: RestrictedPolicy) -> Mapping[str, object]:
    return {
        "primary_weapon_id": policy.primary_weapon_id,
        "ko_weapon_id": policy.ko_weapon_id,
        "eat_threshold": policy.eat_threshold,
        "ko_threshold": policy.ko_threshold,
        "food_preference": policy.food_preference,
        "repot_when_boost_at_or_below": policy.repot_when_boost_at_or_below,
    }


def _inventory_options(plan: BuildPlan, *, capacity: int) -> tuple[InventoryPlan, ...]:
    """Return a small, deterministic inventory frontier for duel policies.

    This is intentionally a bounded candidate family, rather than an implicit
    claim of exhaustive inventory optimisation.  Every selected inventory is
    full after weapon switches are reserved, so the report remains directly
    actionable and resource telemetry has a stable denominator.
    """
    slots = plan.kit.available_inventory_slots(capacity)
    if slots < 1:
        raise DataUnavailableError("Combat kit leaves no usable inventory slots")
    potion_slots = 1 if plan.primary_style.damage_type != "ranged" or plan.ko_style.damage_type != "ranged" else 0
    food_slots = slots - potion_slots
    options = {
        InventoryPlan(swordfish=slots),
        InventoryPlan(anchovy_pizza=slots),
        InventoryPlan(swordfish=slots // 2, anchovy_pizza=slots - slots // 2),
    }
    if potion_slots:
        options.update(
            {
                InventoryPlan(swordfish=food_slots, strength_potion=1),
                InventoryPlan(anchovy_pizza=food_slots, strength_potion=1),
                InventoryPlan(
                    swordfish=food_slots // 2,
                    anchovy_pizza=food_slots - food_slots // 2,
                    strength_potion=1,
                ),
            }
        )
    return tuple(sorted(options, key=lambda item: (item.strength_potion, item.swordfish, item.anchovy_pizza)))


def supported_preflight(ruleset: Ruleset) -> None:
    ruleset.verify_source_archive()
    ruleset.mechanics.check_required(SUPPORTED_REQUIRED_MECHANICS)
    retained_foods = {option.consumable_id for option in prune_dominated_foods(ruleset.consumables).retained}
    supported_foods = {"anchovy_pizza", "swordfish"}
    if retained_foods != supported_foods:
        raise DataUnavailableError(
            "Duel inventory policy does not cover the verified non-dominated F2P foods: "
            f"expected {sorted(supported_foods)}, observed {sorted(retained_foods)}"
        )


def _melee_style(style_id: str) -> SupportedStyle | None:
    if "_" not in style_id:
        return None
    family, attack_type = style_id.split("_", 1)
    if attack_type == "ranged":
        return None
    if family == "accurate":
        return SupportedStyle(style_id, attack_type, 3, 0, 0)
    if family == "aggressive":
        return SupportedStyle(style_id, attack_type, 0, 3, 0)
    if family == "controlled":
        return SupportedStyle(style_id, attack_type, 1, 1, 1)
    if family == "defensive":
        return SupportedStyle(style_id, attack_type, 0, 0, 3)
    return None


def supported_styles_for_item(item: EquipmentItem) -> tuple[SupportedStyle, ...]:
    styles: list[SupportedStyle] = []
    for style_id in item.attack_styles:
        if style_id == "rapid_ranged":
            # The current verified duel timing slice covers rapid shortbows at
            # two tiles. Crossbows and other ranged families stay fail-closed
            # until their projectile tables are promoted.
            if item.weapon_type == "shortbow":
                styles.append(SupportedStyle(style_id, "ranged", 0, 0, 0))
            continue
        melee = _melee_style(style_id)
        if melee is not None:
            styles.append(melee)
    return tuple(styles)


def default_opening_distances(kit: CombatKit) -> tuple[int, ...]:
    if kit.primary_weapon.weapon_type == "shortbow":
        return (2,)
    return (1,)


def resolve_supported_style(item: EquipmentItem, style_id: str) -> SupportedStyle:
    supported = {style.style_id: style for style in supported_styles_for_item(item)}
    try:
        return supported[style_id]
    except KeyError as error:
        raise DataUnavailableError(
            f"{item.name} does not support the verified style {style_id!r} in the current solver slice"
        ) from error


def _validate_build_plan(plan: BuildPlan) -> None:
    if plan.kit.primary_weapon.item_id == plan.kit.ko_weapon.item_id:
        if plan.primary_style != plan.ko_style:
            raise DataUnavailableError(
                "One weapon cannot change attack styles through the supported weapon-switch action"
            )
        if plan.kit.primary_loadout.canonical_id != plan.kit.ko_loadout.canonical_id:
            raise DataUnavailableError(
                "The supported weapon-switch action cannot change ammunition or other worn items "
                "while keeping the same weapon"
            )


def _defence_bonus_map(bonuses: Mapping[str, int]) -> Mapping[str, int]:
    return {
        "defence_stab": bonuses.get("defence_stab", 0),
        "defence_slash": bonuses.get("defence_slash", 0),
        "defence_crush": bonuses.get("defence_crush", 0),
        "defence_ranged": bonuses.get("defence_ranged", 0),
    }


def _build_melee_timing(item: EquipmentItem, ruleset: Ruleset) -> VerifiedAttackTiming:
    if item.attack_speed is None:
        raise DataUnavailableError(f"{item.name} has no verified melee attack speed")
    timing = ImpactTiming.from_mechanic(ruleset.mechanics.require("melee.damage_timing"))
    return VerifiedAttackTiming(
        cooldown_ticks=item.attack_speed,
        impact_delay_by_distance=timing.impact_delay_by_distance,
        minimum_distance=timing.minimum_distance,
        maximum_distance=timing.maximum_distance,
        source_ids=timing.source_ids,
        status="verified",
    )


def _build_shortbow_rapid_timing(item: EquipmentItem, ruleset: Ruleset) -> VerifiedAttackTiming:
    if item.attack_speed is None:
        raise DataUnavailableError(f"{item.name} has no verified ranged attack speed")
    cooldown = ruleset.mechanics.evaluate("ranged.rapid_attack_cooldown", {"base_attack_speed": item.attack_speed})
    cooldown_ticks = int(cooldown)
    timing = ImpactTiming.from_mechanic(ruleset.mechanics.require("ranged.projectile_timing"))
    return VerifiedAttackTiming(
        cooldown_ticks=cooldown_ticks,
        impact_delay_by_distance=timing.impact_delay_by_distance,
        minimum_distance=timing.minimum_distance,
        maximum_distance=timing.maximum_distance,
        source_ids=timing.source_ids,
        status="verified",
    )


def build_supported_profile(
    ruleset: Ruleset,
    account: AccountState,
    item: EquipmentItem,
    style: SupportedStyle,
    *,
    ranged_strength_bonus: int = 0,
    target: TargetDefence = _PLAYER_DEFENCE_PLACEHOLDER,
    equipment_bonuses: Mapping[str, int] | None = None,
) -> AttackProfile:
    bonuses = equipment_bonuses if equipment_bonuses is not None else item.bonuses
    if style.damage_type == "ranged":
        if item.weapon_type != "shortbow" or style.style_id != "rapid_ranged":
            raise DataUnavailableError(f"{item.name} does not have supported ranged timing for {style.style_id}")
        ranged_strength = bonuses.get("ranged_strength", 0)
        if equipment_bonuses is None:
            ranged_strength += ranged_strength_bonus
        profile = build_ranged_profile(
            ruleset.mechanics,
            RangedProfileInput(
                weapon_id=item.item_id,
                ranged_level=account.ranged_level,
                ranged_attack_bonus=bonuses.get("attack_ranged", 0),
                ranged_strength_bonus=ranged_strength,
                timing=_build_shortbow_rapid_timing(item, ruleset),
            ),
            target,
        )
        return AttackProfile(
            profile.weapon_id,
            profile.damage_type,
            profile.attack_roll,
            profile.defence_roll,
            profile.hit_chance,
            profile.max_hit,
            profile.timing,
            profile.successful_zero_becomes_one,
            profile.formula_versions,
            profile.dynamic_melee,
            style.defence_style_bonus,
        )
    attack_bonus_name = f"attack_{style.damage_type}"
    profile = build_melee_profile(
        ruleset.mechanics,
        MeleeProfileInput(
            weapon_id=item.item_id,
            attack_type=style.damage_type,
            attack_level=account.attack_level,
            strength_level=account.strength_level,
            attack_bonus=bonuses.get(attack_bonus_name, 0),
            strength_bonus=bonuses.get("melee_strength", 0),
            timing=_build_melee_timing(item, ruleset),
            attack_style_bonus=style.attack_style_bonus,
            strength_style_bonus=style.strength_style_bonus,
        ),
        target,
    )
    return AttackProfile(
        profile.weapon_id,
        profile.damage_type,
        profile.attack_roll,
        profile.defence_roll,
        profile.hit_chance,
        profile.max_hit,
        profile.timing,
        profile.successful_zero_becomes_one,
        profile.formula_versions,
        profile.dynamic_melee,
        style.defence_style_bonus,
    )


def build_plan_actor(ruleset: Ruleset, plan: BuildPlan) -> DuelActor:
    _validate_build_plan(plan)
    profiles = {}
    defence_bonuses = {}
    for purpose, weapon, style in (
        ("primary", plan.kit.primary_weapon, plan.primary_style),
        ("ko", plan.kit.ko_weapon, plan.ko_style),
    ):
        equipped_bonuses = plan.kit.equipped_bonuses(purpose)
        profile = build_supported_profile(
            ruleset,
            plan.account,
            weapon,
            style,
            equipment_bonuses=equipped_bonuses,
        )
        profiles[weapon.item_id] = profile
        defence_bonuses[weapon.item_id] = _defence_bonus_map(equipped_bonuses)
    inventory = plan.inventory.build(
        capacity=ruleset.inventory_slots,
        reserved_switch_slots=plan.kit.inventory_slots,
    )
    if any(entry.item_id == "strength_potion" for entry in inventory.entries):
        decay = int(ruleset.mechanics.require("boost.combat_decay_interval_ticks").value)
        base_strength = plan.account.strength_level
        visible_strength = plan.account.strength_level
    else:
        decay = None
        base_strength = None
        visible_strength = None
    return DuelActor(
        hp=plan.account.hitpoints_level,
        max_hp=plan.account.hitpoints_level,
        active_weapon_id=plan.kit.primary_weapon.item_id,
        weapons=profiles,
        weapon_defence_bonuses=defence_bonuses,
        inventory=inventory,
        defence_level=plan.account.defence_level,
        base_strength=base_strength,
        visible_strength=visible_strength,
        combat_boost_decay_remaining=decay,
    )


def default_policy_grid(actor: DuelActor, plan: BuildPlan) -> tuple[RestrictedPolicy, ...]:
    primary = actor.weapons[plan.kit.primary_weapon.item_id]
    ko = actor.weapons[plan.kit.ko_weapon.item_id]
    max_hp = plan.account.hitpoints_level
    candidate_eat_thresholds = sorted(
        {
            max(0, min(max_hp, value))
            for value in (
                0,
                primary.max_hit + 1,
                ko.max_hit + 1,
                primary.max_hit + ko.max_hit,
                max_hp // 2,
            )
        }
    )
    candidate_ko_thresholds = sorted(
        {
            max(0, min(max_hp, value))
            for value in (
                0,
                ko.max_hit,
                primary.max_hit + ko.max_hit,
                max_hp // 2,
            )
        }
    )
    repot_thresholds: Sequence[int | None]
    if plan.inventory.strength_potion:
        repot_thresholds = (None, 1)
    else:
        repot_thresholds = (None,)
    return enumerate_restricted_policies(
        plan.kit.primary_weapon.item_id,
        plan.kit.ko_weapon.item_id,
        eat_thresholds=candidate_eat_thresholds,
        ko_thresholds=candidate_ko_thresholds,
        food_preferences=(("anchovy_pizza", "swordfish"), ("swordfish", "anchovy_pizza")),
        repot_thresholds=repot_thresholds,
    )


def optimize_supported_matchup(
    ruleset: Ruleset,
    player_plan: BuildPlan,
    opponent_plan: BuildPlan,
    *,
    samples: int,
    seed: int,
    maximum_ticks: int = 200,
    maximum_iterations: int = 6,
) -> SupportedMatchupResult:
    supported_preflight(ruleset)
    ruleset.mechanics.check_required(
        (
            "tick.pipeline",
            "death.simultaneous_ko",
            "melee.damage_timing",
            "ranged.projectile_timing",
        )
    )
    _validate_build_plan(player_plan)
    _validate_build_plan(opponent_plan)
    supported_distance = max(player_plan.opening_distance, opponent_plan.opening_distance)
    player_plan = replace(player_plan, opening_distance=supported_distance)
    opponent_plan = replace(opponent_plan, opening_distance=supported_distance)
    consumables = {item["consumable_id"]: item for item in ruleset.consumables}
    simulator = DuelSimulator(
        DuelRules.from_mechanics(
            ruleset.mechanics,
            maximum_ticks=maximum_ticks,
            switch_and_attack_same_tick=True,
        ),
        consumables=consumables,
        mechanics=ruleset.mechanics,
    )
    player_options = tuple(
        BuildPlan(
            account=player_plan.account,
            kit=player_plan.kit,
            primary_style=player_plan.primary_style,
            ko_style=player_plan.ko_style,
            inventory=inventory,
            opening_distance=player_plan.opening_distance,
        )
        for inventory in _inventory_options(player_plan, capacity=ruleset.inventory_slots)
    )
    opponent_options = tuple(
        BuildPlan(
            account=opponent_plan.account,
            kit=opponent_plan.kit,
            primary_style=opponent_plan.primary_style,
            ko_style=opponent_plan.ko_style,
            inventory=inventory,
            opening_distance=opponent_plan.opening_distance,
        )
        for inventory in _inventory_options(opponent_plan, capacity=ruleset.inventory_slots)
    )
    player_actors = {option.inventory: build_plan_actor(ruleset, option) for option in player_options}
    opponent_actors = {option.inventory: build_plan_actor(ruleset, option) for option in opponent_options}
    player_policy_sets = {
        option.inventory: default_policy_grid(player_actors[option.inventory], option) for option in player_options
    }
    opponent_policy_sets = {
        option.inventory: default_policy_grid(opponent_actors[option.inventory], option) for option in opponent_options
    }
    cache: dict[tuple[InventoryPlan, RestrictedPolicy, InventoryPlan, RestrictedPolicy], ResourceMatchupResult] = {}

    def evaluate(
        player_inventory: InventoryPlan,
        player_policy: RestrictedPolicy,
        opponent_inventory: InventoryPlan,
        opponent_policy: RestrictedPolicy,
    ) -> ResourceMatchupResult:
        key = (player_inventory, player_policy, opponent_inventory, opponent_policy)
        if key not in cache:
            cache[key] = simulate_matchup_with_resources(
                simulator,
                lambda: DuelState(
                    0,
                    player_actors[player_inventory],
                    opponent_actors[opponent_inventory],
                    player_plan.opening_distance,
                ),
                player_policy,
                opponent_policy,
                samples=samples,
                seed=seed,
            )
        return cache[key]

    player_inventory = player_options[0].inventory
    opponent_inventory = opponent_options[0].inventory
    player_policy = player_policy_sets[player_inventory][0]
    opponent_policy = opponent_policy_sets[opponent_inventory][0]
    player_evaluation = 0.0
    opponent_evaluation = 0.0
    last_matchup: ResourceMatchupResult | None = None
    for iteration in range(1, maximum_iterations + 1):  # noqa: B007  # reported after the loop
        player_best_objective = -1.0
        for option in player_options:
            best_player, _ = optimize_restricted_policy(
                player_policy_sets[option.inventory],
                # Bind the incumbent opponent now; the closure is consumed immediately.
                lambda policy, inventory=option.inventory, versus=(opponent_inventory, opponent_policy): (
                    evaluate(
                        inventory,
                        policy,
                        *versus,
                    ).matchup.win_probability
                ),
            )
            if best_player.objective > player_best_objective:
                player_best_objective = best_player.objective
                player_inventory = option.inventory
                player_policy = best_player.policy
        player_evaluation = player_best_objective
        opponent_best_objective = -1.0
        for option in opponent_options:
            best_opponent, _ = optimize_restricted_policy(
                opponent_policy_sets[option.inventory],
                # Bind the incumbent player now; the closure is consumed immediately.
                lambda policy, inventory=option.inventory, versus=(player_inventory, player_policy): (
                    evaluate(
                        *versus,
                        inventory,
                        policy,
                    ).matchup.loss_probability
                ),
            )
            if best_opponent.objective > opponent_best_objective:
                opponent_best_objective = best_opponent.objective
                opponent_inventory = option.inventory
                opponent_policy = best_opponent.policy
        opponent_evaluation = opponent_best_objective
        updated = evaluate(player_inventory, player_policy, opponent_inventory, opponent_policy)
        if last_matchup is not None and updated.matchup == last_matchup.matchup:
            last_matchup = updated
            break
        last_matchup = updated
    if last_matchup is None:
        raise DataUnavailableError("Policy search did not evaluate any supported matchups")
    return SupportedMatchupResult(
        PolicySearchResult(player_policy, player_evaluation, iteration),
        PolicySearchResult(opponent_policy, opponent_evaluation, iteration),
        last_matchup,
    )


def _strategy_descriptor(
    ruleset: Ruleset,
    plan: BuildPlan,
    policy: RestrictedPolicy,
) -> StrategyDescriptor:
    inventory = plan.inventory.build(
        capacity=ruleset.inventory_slots,
        reserved_switch_slots=plan.kit.inventory_slots,
    )
    payload = {
        "account_id": plan.account.canonical_id,
        "kit_id": plan.kit.canonical_id,
        "inventory_id": inventory.canonical_id,
        "opening_distance": plan.opening_distance,
        "primary_style": plan.primary_style.style_id,
        "ko_style": plan.ko_style.style_id,
        "policy": _policy_document(policy),
    }
    return StrategyDescriptor(
        strategy_id=canonical_hash(payload),
        account_id=plan.account.canonical_id,
        combat_level=plan.account.combat_level(ruleset.mechanics),
        attack_level=plan.account.attack_level,
        strength_level=plan.account.strength_level,
        ranged_level=plan.account.ranged_level,
        magic_level=plan.account.magic_level,
        prayer_level=plan.account.prayer_level,
        hitpoints_level=plan.account.hitpoints_level,
        primary_weapon={
            "item_id": plan.kit.primary_weapon.item_id,
            "name": plan.kit.primary_weapon.name,
            "style_id": plan.primary_style.style_id,
        },
        ko_weapon={
            "item_id": plan.kit.ko_weapon.item_id,
            "name": plan.kit.ko_weapon.name,
            "style_id": plan.ko_style.style_id,
        },
        ammunition=None
        if plan.kit.ammunition is None
        else {
            "item_id": plan.kit.ammunition.item_id,
            "name": plan.kit.ammunition.name,
        },
        inventory_entries=tuple(
            {
                "item_id": entry.item_id,
                "state": entry.state,
                "quantity": entry.quantity,
                "stackable": entry.stackable,
            }
            for entry in inventory.entries
        ),
        reserved_switch_slots=plan.kit.inventory_slots,
        policy={**_policy_document(policy), "opening_distance": plan.opening_distance},
    )


def materialize_supported_strategies(
    ruleset: Ruleset,
    accounts: Sequence[AccountState],
    *,
    maximum_strategies: int,
    context: LegalityContext = LegalityContext(),
) -> tuple[DuelStrategyCandidate, ...]:
    """Build a deterministic, bounded set of executable melee/ranged strategies.

    The limit is an explicit search scope, recorded in the eventual report; it
    never means that unexamined policies were dominance-pruned.
    """
    if maximum_strategies < 1:
        raise ValueError("maximum_strategies must be positive")
    items = tuple(
        EquipmentItem.from_document_with_policy(
            document,
            allow_unverified=True,
        )
        for document in ruleset.items
    )
    groups: list[tuple[DuelStrategyCandidate, ...]] = []
    for account in accounts:
        for kit in generate_combat_kits(account, items, context=context).kits:
            primary_styles = supported_styles_for_item(kit.primary_weapon)
            ko_styles = supported_styles_for_item(kit.ko_weapon)
            for primary_style in primary_styles:
                for ko_style in ko_styles:
                    # Style changes on the same equipped weapon are not an
                    # available action in this reduced policy language.
                    if kit.primary_weapon.item_id == kit.ko_weapon.item_id and primary_style != ko_style:
                        continue
                    base = BuildPlan(
                        account=account,
                        kit=kit,
                        primary_style=primary_style,
                        ko_style=ko_style,
                        inventory=InventoryPlan(),
                        opening_distance=default_opening_distances(kit)[0],
                    )
                    try:
                        _validate_build_plan(base)
                    except DataUnavailableError:
                        continue
                    for inventory in _inventory_options(base, capacity=ruleset.inventory_slots):
                        plan = BuildPlan(
                            account=account,
                            kit=kit,
                            primary_style=primary_style,
                            ko_style=ko_style,
                            inventory=inventory,
                            opening_distance=base.opening_distance,
                        )
                        actor = build_plan_actor(ruleset, plan)
                        group: list[DuelStrategyCandidate] = []
                        for policy in default_policy_grid(actor, plan):
                            descriptor = _strategy_descriptor(ruleset, plan, policy)
                            group.append(DuelStrategyCandidate(StrategyCandidate(descriptor), plan, policy))
                        groups.append(tuple(group))
    if not groups:
        raise DataUnavailableError("No supported melee/ranged strategies fit the requested account scope")
    # Take one policy from every build/inventory before considering a second
    # policy. This avoids a small search budget accidentally becoming a report
    # about one inventory simply because it was generated first.
    strategies: list[DuelStrategyCandidate] = []
    round_index = 0
    while len(strategies) < maximum_strategies:
        added = False
        for group in groups:
            if round_index < len(group):
                strategies.append(group[round_index])
                added = True
                if len(strategies) == maximum_strategies:
                    break
        if not added:
            break
        round_index += 1
    return tuple(strategies)


def materialize_supported_strategy_pool(
    ruleset: Ruleset,
    accounts: Sequence[AccountState],
    *,
    maximum_strategies: int,
    context: LegalityContext = LegalityContext(),
) -> tuple[DuelStrategyCandidate, ...]:
    """Stream one placeholder candidate per distinct executable build into a pool.

    This is the low-memory candidate-universe builder for the active solver.
    Diverse seed selection happens after materialization, while pairwise
    inventory/policy optimisation remains deferred to the active payoff oracle.
    """
    if maximum_strategies < 1:
        raise ValueError("maximum_strategies must be positive")
    items = tuple(
        EquipmentItem.from_document_with_policy(document, allow_unverified=True) for document in ruleset.items
    )
    strategies: list[DuelStrategyCandidate] = []
    for account in accounts:
        for kit in generate_combat_kits(account, items, context=context).kits:
            for primary_style in supported_styles_for_item(kit.primary_weapon):
                for ko_style in supported_styles_for_item(kit.ko_weapon):
                    if kit.primary_weapon.item_id == kit.ko_weapon.item_id and primary_style != ko_style:
                        continue
                    base = BuildPlan(
                        account=account,
                        kit=kit,
                        primary_style=primary_style,
                        ko_style=ko_style,
                        inventory=InventoryPlan(),
                        opening_distance=default_opening_distances(kit)[0],
                    )
                    try:
                        _validate_build_plan(base)
                    except DataUnavailableError:
                        continue
                    inventory = _inventory_options(base, capacity=ruleset.inventory_slots)[0]
                    plan = replace(base, inventory=inventory)
                    actor = build_plan_actor(ruleset, plan)
                    policies = default_policy_grid(actor, plan)
                    if not policies:
                        continue
                    policy = policies[0]
                    strategies.append(
                        DuelStrategyCandidate(
                            StrategyCandidate(_strategy_descriptor(ruleset, plan, policy)),
                            plan,
                            policy,
                        )
                    )
                    if len(strategies) >= maximum_strategies:
                        return tuple(strategies)
    if not strategies:
        raise DataUnavailableError("No supported melee/ranged strategies fit the requested account scope")
    return tuple(strategies)


def solve_supported_strategy_space(
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
    maximum_strategies: int = 32,
    account_mode: str = "f2p_standard_training",
    allow_wiki_first: bool = False,
) -> SolveReport:
    """Run the verified duel engine over a bounded melee/ranged strategy set.

    This compatibility path deliberately retains its explicit strategy budget.
    The sparse double-oracle coordinator lives in :mod:`pure_solver.double_oracle`
    and must be supplied a fully screened candidate universe and payoff oracle;
    this function does not relabel a truncated set as exhaustive.
    """
    ruleset.preflight(DUEL_REQUIRED_MECHANICS, allow_unverified_items=allow_wiki_first)
    supported_preflight(ruleset)
    context = LegalityContext(allow_unverified_items=allow_wiki_first)
    if samples < 1:
        raise ValueError("Duel strategy solving requires at least one sample")
    if account_mode not in {"independent_hp", "f2p_standard_training"}:
        raise ValueError(f"Unknown account mode {account_mode!r}")
    enumerated_accounts = enumerate_account_states(
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
    accounts_list: list[AccountState] = []
    for account in enumerated_accounts:
        if account_mode == "f2p_standard_training" and not standard_f2p_hitpoints_achievable(
            account, ruleset.mechanics
        ):
            continue
        if maximum_accounts is not None and len(accounts_list) >= maximum_accounts:
            raise SearchBudgetExceeded(
                f"Account search reached its explicit {maximum_accounts}-candidate budget; result is not exhaustive."
            )
        accounts_list.append(account)
    accounts = tuple(accounts_list)
    strategies = materialize_supported_strategies(
        ruleset,
        accounts,
        maximum_strategies=maximum_strategies,
        context=context,
    )
    consumables = {item["consumable_id"]: item for item in ruleset.consumables}
    simulator = DuelSimulator(
        DuelRules.from_mechanics(
            ruleset.mechanics,
            maximum_ticks=maximum_ticks,
            switch_and_attack_same_tick=True,
        ),
        consumables=consumables,
        mechanics=ruleset.mechanics,
    )
    actors = {item.candidate.descriptor.strategy_id: build_plan_actor(ruleset, item.plan) for item in strategies}
    executable = {item.candidate.descriptor.strategy_id: item for item in strategies}
    cache: dict[tuple[str, str], ResourceMatchupResult] = {}

    def evaluate(row: StrategyCandidate, column: StrategyCandidate) -> ResourceMatchupResult:
        key = (row.descriptor.strategy_id, column.descriptor.strategy_id)
        if key not in cache:
            player = executable[key[0]]
            opponent = executable[key[1]]
            distance = max(player.plan.opening_distance, opponent.plan.opening_distance)
            cache[key] = simulate_matchup_with_resources(
                simulator,
                lambda: DuelState(0, actors[key[0]], actors[key[1]], distance),
                player.policy,
                opponent.policy,
                samples=samples,
                seed=derived_seed(seed, *key),
            )
        return cache[key]

    report = solve_strategy_space(
        ruleset,
        tuple(item.candidate for item in strategies),
        evaluate,
        account_count=len(accounts),
        kit_count=len({item.plan.kit.canonical_id for item in strategies}),
        inventory_count=len({item.plan.inventory for item in strategies}),
        policy_count=len({item.policy for item in strategies}),
        required_mechanics=DUEL_REQUIRED_MECHANICS,
    )
    verification = {
        "status": "provisional" if allow_wiki_first else "verified",
        "production_ready": True,
        "scope": "melee_ranged_duel_strategy_v1",
        "required_mechanics": DUEL_REQUIRED_MECHANICS,
        "candidate_generation": "deterministic_bounded",
        "maximum_accounts": maximum_accounts,
        "maximum_strategies": maximum_strategies,
        "samples_per_matchup": samples,
        "root_seed": seed,
        "account_mode": account_mode,
        "allow_wiki_first": allow_wiki_first,
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
