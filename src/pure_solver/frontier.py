"""Closed-form verified offense frontier: for every account in range and every combat kit, resolve the best
attack style against a fixed target, attach an inventory frontier, and keep a bounded top-N overall and by KO
max hit.

Backs the exploratory ``offense-frontier`` command; it reports offensive output only, not duel outcomes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fractions import Fraction

from .accounts import AccountSearchBounds, AccountState, LevelRange, enumerate_account_states
from .allocations import InventoryAllocation, InventoryOption, generate_inventory_allocations
from .consumable_dominance import prune_dominated_foods
from .errors import DataUnavailableError, VerifiedMechanicMissingError
from .experience import enumerate_standard_f2p_account_states, standard_f2p_hitpoints_achievable
from .kits import CombatKit, generate_combat_kits
from .legality import F2P_STANDARD_WORLD_SCOPE, EquipmentItem, is_item_legal
from .prayers import best_melee_prayer_set, best_ranged_prayer_set, relevant_prayer_levels
from .profiles import (
    MeleeProfileInput,
    OffensiveProfile,
    RangedProfileInput,
    TargetDefence,
    build_melee_offensive_profile,
    build_ranged_offensive_profile,
)
from .ruleset import Ruleset

_INVENTORY_FRONTIER_CACHE: dict[tuple[object, ...], InventoryFrontier] = {}
_STYLE_SNAPSHOT_CACHE: dict[tuple[object, ...], StyleSnapshot] = {}
_CACHE_LIMIT = 200_000


def clear_frontier_caches() -> None:
    _INVENTORY_FRONTIER_CACHE.clear()
    _STYLE_SNAPSHOT_CACHE.clear()


def frontier_cache_sizes() -> Mapping[str, int]:
    return {
        "inventory_frontiers": len(_INVENTORY_FRONTIER_CACHE),
        "style_snapshots": len(_STYLE_SNAPSHOT_CACHE),
    }


def _fraction_document(value: Fraction) -> Mapping[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _style_family(style: str) -> str:
    family, _, _ = style.partition("_")
    if not family:
        raise DataUnavailableError(f"Unsupported attack style {style!r}")
    return family


def _style_damage_type(style: str) -> str:
    _, _, suffix = style.partition("_")
    if suffix not in {"stab", "slash", "crush", "ranged"}:
        raise DataUnavailableError(f"Unsupported attack style {style!r}")
    return suffix


def _is_melee_damage(damage_type: str) -> bool:
    return damage_type in {"stab", "slash", "crush"}


def _protected(damage_type: str, protected_style: str | None) -> bool:
    if protected_style is None:
        return False
    if protected_style == "melee":
        return _is_melee_damage(damage_type)
    return damage_type == protected_style


def _style_bonus_map(ruleset: Ruleset) -> Mapping[str, Mapping[str, int]]:
    value = ruleset.mechanics.require("combat_style.f2p_bonuses").value
    if not isinstance(value, Mapping):
        raise DataUnavailableError("combat_style.f2p_bonuses must be a mapping")
    result: dict[str, Mapping[str, int]] = {}
    for family, entry in value.items():
        if not isinstance(family, str) or not isinstance(entry, Mapping):
            raise DataUnavailableError("combat_style.f2p_bonuses has an invalid family entry")
        result[family] = {str(key): int(number) for key, number in entry.items()}
    return result


@dataclass(frozen=True)
class OffensiveTarget:
    defence_level: int = 1
    stab_defence_bonus: int = 0
    slash_defence_bonus: int = 0
    crush_defence_bonus: int = 0
    ranged_defence_bonus: int = 0
    protected_style: str | None = None
    protection_multiplier: Fraction = Fraction(1)

    def defence_bonus(self, damage_type: str) -> int:
        if damage_type == "stab":
            return self.stab_defence_bonus
        if damage_type == "slash":
            return self.slash_defence_bonus
        if damage_type == "crush":
            return self.crush_defence_bonus
        if damage_type == "ranged":
            return self.ranged_defence_bonus
        raise DataUnavailableError(f"Unsupported damage type {damage_type!r}")

    def target_defence(self, damage_type: str) -> TargetDefence:
        return TargetDefence(
            defence_level=self.defence_level,
            defence_bonus=self.defence_bonus(damage_type),
        )


@dataclass(frozen=True)
class InventoryCapacitySummary:
    allocation: InventoryAllocation
    total_healing: int
    total_actions: int
    total_healing_by_item: Mapping[str, int]
    maximum_actions_by_item: Mapping[str, int]

    def to_document(self) -> Mapping[str, object]:
        return {
            "inventory_id": self.allocation.inventory.canonical_id,
            "reserved_switch_slots": self.allocation.reserved_switch_slots,
            "inventory_slots_used": self.allocation.total_slots_used,
            "remaining_slots": self.allocation.remaining_slots,
            "entries": [
                {
                    "item_id": entry.item_id,
                    "state": entry.state,
                    "quantity": entry.quantity,
                    "stackable": entry.stackable,
                }
                for entry in self.allocation.inventory.entries
            ],
            "total_healing": self.total_healing,
            "total_actions": self.total_actions,
            "total_healing_by_item": dict(sorted(self.total_healing_by_item.items())),
            "maximum_actions_by_item": dict(sorted(self.maximum_actions_by_item.items())),
        }


@dataclass(frozen=True)
class InventoryFrontier:
    by_total_healing: InventoryCapacitySummary
    by_total_actions: InventoryCapacitySummary
    pareto_count: int

    def to_document(self) -> Mapping[str, object]:
        return {
            "pareto_count": self.pareto_count,
            "best_total_healing": self.by_total_healing.to_document(),
            "best_total_actions": self.by_total_actions.to_document(),
        }


@dataclass(frozen=True)
class StyleSnapshot:
    style: str
    profile: OffensiveProfile
    prayer_ids: tuple[str, ...]
    strength_potion: bool

    def to_document(self) -> Mapping[str, object]:
        return {
            "style": self.style,
            "damage_type": self.profile.damage_type,
            "attack_roll": self.profile.attack_roll,
            "defence_roll": self.profile.defence_roll,
            "hit_chance": _fraction_document(self.profile.hit_chance),
            "max_hit": self.profile.max_hit,
            "cooldown_ticks": self.profile.cooldown_ticks,
            "expected_damage_per_attack": _fraction_document(self.profile.expected_damage_per_attack),
            "expected_damage_per_tick": _fraction_document(self.profile.expected_damage_per_tick),
            "expected_damage_per_tick_float": float(self.profile.expected_damage_per_tick),
            "prayer_ids": list(self.prayer_ids),
            "strength_potion": self.strength_potion,
            "formula_versions": list(self.profile.formula_versions),
        }


@dataclass(frozen=True)
class OffensiveCandidate:
    account: AccountState
    combat_level: int
    kit: CombatKit
    primary: StyleSnapshot
    ko: StyleSnapshot
    inventory: InventoryFrontier

    def sort_key(self) -> tuple[Fraction, int, Fraction, int, int, int]:
        return (
            self.primary.profile.expected_damage_per_tick,
            self.primary.profile.max_hit,
            self.ko.profile.max_hit,
            self.ko.profile.expected_damage_per_tick,
            self.inventory.by_total_healing.total_healing,
            self.inventory.by_total_actions.total_actions,
        )

    def to_document(self) -> Mapping[str, object]:
        inventory_capacity = self.inventory.by_total_healing.allocation.inventory.capacity
        return {
            "account": {
                "attack": self.account.attack_level,
                "strength": self.account.strength_level,
                "ranged": self.account.ranged_level,
                "magic": self.account.magic_level,
                "prayer": self.account.prayer_level,
                "hitpoints": self.account.hitpoints_level,
                "defence": self.account.defence_level,
                "account_id": self.account.canonical_id,
            },
            "combat_level": self.combat_level,
            "kit": {
                "kit_id": self.kit.canonical_id,
                "primary_weapon": self.kit.primary_weapon.name,
                "primary_weapon_id": self.kit.primary_weapon.item_id,
                "ko_weapon": self.kit.ko_weapon.name,
                "ko_weapon_id": self.kit.ko_weapon.item_id,
                "ammunition": self.kit.ammunition.name if self.kit.ammunition else None,
                "ammunition_id": self.kit.ammunition.item_id if self.kit.ammunition else None,
                "primary_ammunition": self.kit.primary_ammunition.name if self.kit.primary_ammunition else None,
                "primary_ammunition_id": self.kit.primary_ammunition.item_id if self.kit.primary_ammunition else None,
                "ko_ammunition": self.kit.ko_ammunition.name if self.kit.ko_ammunition else None,
                "ko_ammunition_id": self.kit.ko_ammunition.item_id if self.kit.ko_ammunition else None,
                "common_worn_items": [
                    {"item_id": item.item_id, "name": item.name, "slot": item.slot}
                    for item in self.kit.common_worn_items
                ],
                "primary_loadout": [
                    {"item_id": item.item_id, "name": item.name, "slot": item.slot}
                    for item in self.kit.primary_loadout.items
                ],
                "ko_loadout": [
                    {"item_id": item.item_id, "name": item.name, "slot": item.slot}
                    for item in self.kit.ko_loadout.items
                ],
                "inventory_slots": self.kit.inventory_slots,
                "available_inventory_slots": self.kit.available_inventory_slots(inventory_capacity),
            },
            "primary": self.primary.to_document(),
            "ko": self.ko.to_document(),
            "inventory_frontier": self.inventory.to_document(),
        }


def _inventory_transition_totals(
    item_id: str,
    state: str,
    consumables: Mapping[str, Mapping[str, object]],
) -> tuple[int, int]:
    document = consumables.get(item_id)
    if (
        document is None
        or document.get("status") != "verified"
        or document.get("availability_scope") != F2P_STANDARD_WORLD_SCOPE
        or not document.get("source_ids")
    ):
        raise VerifiedMechanicMissingError(f"Consumable {item_id!r} is unavailable or not verified")
    transitions = document.get("transitions")
    if not isinstance(transitions, Mapping):
        raise DataUnavailableError(f"Consumable {item_id!r} has no transition graph")
    healing = 0
    actions = 0
    current_item = item_id
    current_state = state
    seen: set[tuple[str, str]] = set()
    while True:
        identity = (current_item, current_state)
        if identity in seen:
            raise DataUnavailableError(f"Consumable {item_id!r} contains a transition loop")
        seen.add(identity)
        current = consumables.get(current_item)
        if current is None:
            raise DataUnavailableError(f"Consumable transition references missing item {current_item!r}")
        current_transitions = current.get("transitions")
        if not isinstance(current_transitions, Mapping):
            raise DataUnavailableError(f"Consumable {current_item!r} has no transition graph")
        transition = current_transitions.get(current_state)
        if not isinstance(transition, Mapping):
            return healing, actions
        actions += 1
        healing_value = transition.get("healing", 0)
        if not isinstance(healing_value, int) or healing_value < 0:
            raise DataUnavailableError(f"Consumable {current_item!r} has invalid healing data")
        healing += healing_value
        next_state = transition.get("next_state")
        if next_state is None:
            return healing, actions
        next_item = str(transition.get("next_item_id", current_item))
        if next_item not in consumables:
            return healing, actions
        current_item = next_item
        current_state = str(next_state)


def _inventory_summary(
    allocation: InventoryAllocation,
    consumables: Mapping[str, Mapping[str, object]],
) -> InventoryCapacitySummary:
    total_healing = 0
    total_actions = 0
    healing_by_item: dict[str, int] = {}
    actions_by_item: dict[str, int] = {}
    for entry in allocation.inventory.entries:
        healing_per_unit, actions_per_unit = _inventory_transition_totals(entry.item_id, entry.state, consumables)
        healing = healing_per_unit * entry.quantity
        actions = actions_per_unit * entry.quantity
        total_healing += healing
        total_actions += actions
        healing_by_item[entry.item_id] = healing_by_item.get(entry.item_id, 0) + healing
        actions_by_item[entry.item_id] = actions_by_item.get(entry.item_id, 0) + actions
    return InventoryCapacitySummary(
        allocation=allocation,
        total_healing=total_healing,
        total_actions=total_actions,
        total_healing_by_item=healing_by_item,
        maximum_actions_by_item=actions_by_item,
    )


def _inventory_frontier(
    ruleset: Ruleset,
    kit: CombatKit,
    *,
    use_strength_potion: bool,
) -> InventoryFrontier:
    cache_key = (
        ruleset.ruleset_id,
        ruleset.item_database_hash,
        ruleset.consumable_database_hash,
        ruleset.inventory_slots,
        kit.canonical_id,
        use_strength_potion,
    )
    cached = _INVENTORY_FRONTIER_CACHE.get(cache_key)
    if cached is not None:
        return cached
    food_search = prune_dominated_foods(ruleset.consumables)
    options = [
        InventoryOption(food.consumable_id, food.initial_state, 0, ruleset.inventory_slots)
        for food in food_search.retained
    ]
    if use_strength_potion:
        options.append(InventoryOption("strength_potion", "4_dose", 1, 1))
    allocations = generate_inventory_allocations(
        kit,
        options,
        capacity=ruleset.inventory_slots,
        fill_capacity=True,
    )
    consumables = {item["consumable_id"]: item for item in ruleset.consumables}
    summaries = tuple(_inventory_summary(allocation, consumables) for allocation in allocations)
    if not summaries:
        raise DataUnavailableError("Verified inventory frontier is empty")
    pareto: list[InventoryCapacitySummary] = []
    for summary in summaries:
        if any(
            other.total_healing >= summary.total_healing
            and other.total_actions >= summary.total_actions
            and (other.total_healing > summary.total_healing or other.total_actions > summary.total_actions)
            for other in summaries
        ):
            continue
        pareto.append(summary)
    by_total_healing = max(
        pareto,
        key=lambda item: (item.total_healing, item.total_actions, -item.allocation.remaining_slots),
    )
    by_total_actions = max(
        pareto,
        key=lambda item: (item.total_actions, item.total_healing, -item.allocation.remaining_slots),
    )
    result = InventoryFrontier(by_total_healing, by_total_actions, len(pareto))
    if len(_INVENTORY_FRONTIER_CACHE) >= _CACHE_LIMIT:
        _INVENTORY_FRONTIER_CACHE.clear()
    _INVENTORY_FRONTIER_CACHE[cache_key] = result
    return result


def _ranged_cooldown(ruleset: Ruleset, item: EquipmentItem, family: str) -> int:
    if item.attack_speed is None:
        raise VerifiedMechanicMissingError(f"Item {item.name!r} has no verified attack speed")
    if family == "rapid":
        cooldown = ruleset.mechanics.evaluate(
            "ranged.rapid_attack_cooldown",
            {"base_attack_speed": item.attack_speed},
        )
        if not isinstance(cooldown, int):
            raise DataUnavailableError("Rapid ranged cooldown must resolve to an integer")
        return cooldown
    return item.attack_speed


def _style_snapshot(
    item: EquipmentItem,
    style: str,
    ruleset: Ruleset,
    target: OffensiveTarget,
    account: AccountState,
    *,
    equipment_bonuses: Mapping[str, int],
    strength_potion: bool,
) -> StyleSnapshot:
    cache_key = (
        ruleset.ruleset_id,
        ruleset.mechanics_database_hash,
        item.item_id,
        tuple(sorted(equipment_bonuses.items())),
        item.attack_speed,
        style,
        target,
        account.attack_level,
        account.strength_level,
        account.ranged_level,
        account.prayer_level,
        strength_potion,
    )
    cached = _STYLE_SNAPSHOT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    family = _style_family(style)
    bonuses = _style_bonus_map(ruleset).get(family)
    if bonuses is None:
        raise VerifiedMechanicMissingError(f"Attack style family {family!r} is not verified")
    damage_type = _style_damage_type(style)
    protection_multiplier = (
        target.protection_multiplier if _protected(damage_type, target.protected_style) else Fraction(1)
    )
    if damage_type == "ranged":
        prayer_set = best_ranged_prayer_set(ruleset.mechanics, account.prayer_level)
        profile = build_ranged_offensive_profile(
            ruleset.mechanics,
            RangedProfileInput(
                weapon_id=item.item_id,
                ranged_level=account.ranged_level,
                ranged_attack_bonus=equipment_bonuses.get("attack_ranged", 0),
                ranged_strength_bonus=equipment_bonuses.get("ranged_strength", 0),
                timing=None,  # type: ignore[arg-type]
                style_bonus=bonuses.get("attack", 0),
                accuracy_prayer_multiplier=prayer_set.multiplier,
                strength_prayer_multiplier=prayer_set.multiplier,
            ),
            target.target_defence("ranged"),
            cooldown_ticks=_ranged_cooldown(ruleset, item, family),
            damage_multiplier=protection_multiplier,
        )
        result = StyleSnapshot(style, profile, prayer_set.prayer_ids, False)
        if len(_STYLE_SNAPSHOT_CACHE) >= _CACHE_LIMIT:
            _STYLE_SNAPSHOT_CACHE.clear()
        _STYLE_SNAPSHOT_CACHE[cache_key] = result
        return result
    melee_prayer = best_melee_prayer_set(ruleset.mechanics, account.prayer_level)
    strength_boost = (
        int(ruleset.mechanics.evaluate("strength_potion.boost", {"base_strength": account.strength_level}))
        if strength_potion
        else 0
    )
    profile = build_melee_offensive_profile(
        ruleset.mechanics,
        MeleeProfileInput(
            weapon_id=item.item_id,
            attack_type=damage_type,
            attack_level=account.attack_level,
            strength_level=account.strength_level,
            attack_bonus=equipment_bonuses.get(f"attack_{damage_type}", 0),
            strength_bonus=equipment_bonuses.get("melee_strength", 0),
            timing=None,  # type: ignore[arg-type]
            strength_boost=strength_boost,
            attack_prayer_multiplier=melee_prayer.attack_multiplier,
            strength_prayer_multiplier=melee_prayer.strength_multiplier,
            attack_style_bonus=bonuses.get("attack", 0),
            strength_style_bonus=bonuses.get("strength", 0),
        ),
        target.target_defence(damage_type),
        cooldown_ticks=item.attack_speed or 0,
        damage_multiplier=protection_multiplier,
    )
    result = StyleSnapshot(style, profile, melee_prayer.prayer_ids, strength_potion)
    if len(_STYLE_SNAPSHOT_CACHE) >= _CACHE_LIMIT:
        _STYLE_SNAPSHOT_CACHE.clear()
    _STYLE_SNAPSHOT_CACHE[cache_key] = result
    return result


def _best_style(
    item: EquipmentItem,
    ruleset: Ruleset,
    target: OffensiveTarget,
    account: AccountState,
    *,
    equipment_bonuses: Mapping[str, int],
    purpose: str,
    strength_potion: bool,
) -> StyleSnapshot:
    if not item.attack_styles:
        raise VerifiedMechanicMissingError(f"Item {item.name!r} has no verified attack styles")
    snapshots = tuple(
        _style_snapshot(
            item,
            style,
            ruleset,
            target,
            account,
            equipment_bonuses=equipment_bonuses,
            strength_potion=strength_potion,
        )
        for style in item.attack_styles
    )
    if purpose == "primary":
        return max(
            snapshots,
            key=lambda snapshot: (
                snapshot.profile.expected_damage_per_tick,
                snapshot.profile.max_hit,
                snapshot.profile.expected_damage_per_attack,
            ),
        )
    if purpose == "ko":
        return max(
            snapshots,
            key=lambda snapshot: (
                snapshot.profile.max_hit,
                snapshot.profile.expected_damage_per_tick,
                snapshot.profile.expected_damage_per_attack,
            ),
        )
    raise ValueError(f"Unknown style selection purpose {purpose!r}")


def _candidate_for_kit(
    ruleset: Ruleset,
    account: AccountState,
    kit: CombatKit,
    target: OffensiveTarget,
    *,
    strength_potion: bool,
) -> OffensiveCandidate:
    primary = _best_style(
        kit.primary_weapon,
        ruleset,
        target,
        account,
        equipment_bonuses=kit.equipped_bonuses("primary"),
        purpose="primary",
        strength_potion=strength_potion,
    )
    ko = _best_style(
        kit.ko_weapon,
        ruleset,
        target,
        account,
        equipment_bonuses=kit.equipped_bonuses("ko"),
        purpose="ko",
        strength_potion=strength_potion,
    )
    return OffensiveCandidate(
        account=account,
        combat_level=account.combat_level(ruleset.mechanics),
        kit=kit,
        primary=primary,
        ko=ko,
        inventory=_inventory_frontier(ruleset, kit, use_strength_potion=strength_potion),
    )


def _prune_kits_for_report_limit(
    kits: tuple[CombatKit, ...],
    ruleset: Ruleset,
    account: AccountState,
    target: OffensiveTarget,
    *,
    strength_potion: bool,
    limit: int,
) -> tuple[CombatKit, ...]:
    """Safely reduce loadout pairs that cannot enter a top-N report."""
    groups: dict[tuple[int, ...], list[CombatKit]] = {}
    for kit in kits:
        common = tuple(
            sorted(
                item.item_id for item in kit.common_worn_items if item.slot not in {"ammo", "weapon", "2h", "shield"}
            )
        )
        groups.setdefault(common, []).append(kit)

    def retained_ids(records: list[CombatKit], purpose: str) -> set[str]:
        ranked: dict[str, tuple[object, ...]] = {}
        for kit in records:
            loadout = kit.primary_loadout if purpose == "primary" else kit.ko_loadout
            loadout_id = loadout.canonical_id
            if loadout_id in ranked:
                continue
            snapshot = _best_style(
                kit.primary_weapon if purpose == "primary" else kit.ko_weapon,
                ruleset,
                target,
                account,
                equipment_bonuses=kit.equipped_bonuses(purpose),
                purpose=purpose,
                strength_potion=strength_potion,
            )
            if purpose == "primary":
                ranked[loadout_id] = (
                    snapshot.profile.expected_damage_per_tick,
                    snapshot.profile.max_hit,
                    snapshot.profile.expected_damage_per_attack,
                )
            else:
                ranked[loadout_id] = (
                    snapshot.profile.max_hit,
                    snapshot.profile.expected_damage_per_tick,
                    snapshot.profile.expected_damage_per_attack,
                )
        ordered = sorted(ranked.values(), reverse=True)
        cutoff = ordered[min(limit, len(ordered)) - 1]
        return {loadout_id for loadout_id, key in ranked.items() if key >= cutoff}

    selected: dict[str, CombatKit] = {}
    for records in groups.values():
        primary_ids = retained_ids(records, "primary")
        ko_ids = retained_ids(records, "ko")
        for kit in records:
            if kit.primary_loadout.canonical_id in primary_ids and kit.ko_loadout.canonical_id in ko_ids:
                selected[kit.canonical_id] = kit
    return tuple(sorted(selected.values(), key=lambda kit: kit.canonical_id))


def _bounded_insert(
    current: list[OffensiveCandidate],
    candidate: OffensiveCandidate,
    limit: int,
    *,
    key: Callable[[OffensiveCandidate], object] | None = None,
) -> None:
    ranking = key or (lambda item: item.sort_key())
    current.append(candidate)
    current.sort(key=ranking, reverse=True)
    if len(current) > limit:
        del current[limit:]


def _supported_items(ruleset: Ruleset) -> tuple[EquipmentItem, ...]:
    return tuple(EquipmentItem.from_document(document) for document in ruleset.items)


def prune_dominated_account_states(
    accounts: tuple[AccountState, ...],
    items: tuple[EquipmentItem, ...],
    ruleset: Ruleset,
) -> tuple[AccountState, ...]:
    """Remove component-wise inferior stats inside identical cost/unlock groups."""
    groups: dict[tuple[object, ...], list[AccountState]] = {}
    for account in accounts:
        legal_signature = tuple(item.item_id for item in items if is_item_legal(item, account))
        key = (
            account.combat_level(ruleset.mechanics),
            account.hitpoints_level,
            account.prayer_level,
            legal_signature,
        )
        frontier = groups.setdefault(key, [])

        def dominates(left: AccountState, right: AccountState) -> bool:
            left_stats = (
                left.attack_level,
                left.strength_level,
                left.ranged_level,
                left.magic_level,
            )
            right_stats = (
                right.attack_level,
                right.strength_level,
                right.ranged_level,
                right.magic_level,
            )
            return all(a >= b for a, b in zip(left_stats, right_stats)) and any(
                a > b for a, b in zip(left_stats, right_stats)
            )

        if any(dominates(existing, account) for existing in frontier):
            continue
        frontier[:] = [existing for existing in frontier if not dominates(account, existing)]
        if all(existing.canonical_id != account.canonical_id for existing in frontier):
            frontier.append(account)
    return tuple(
        sorted(
            (account for frontier in groups.values() for account in frontier),
            key=lambda account: (
                account.combat_level(ruleset.mechanics),
                account.hitpoints_level,
                account.prayer_level,
                account.attack_level,
                account.strength_level,
                account.ranged_level,
                account.magic_level,
            ),
        )
    )


def _solve_bounds(
    ruleset: Ruleset,
    *,
    attack: LevelRange,
    strength: LevelRange,
    ranged: LevelRange,
    prayer: LevelRange,
    hitpoints: LevelRange,
    combat_minimum: int,
    combat_maximum: int,
    max_candidates: int | None,
    account_mode: str = "independent_hp",
) -> list[AccountState]:
    bounds = AccountSearchBounds(
        attack=attack,
        strength=strength,
        ranged=ranged,
        magic=LevelRange(1, 1),
        prayer=prayer,
        hitpoints=hitpoints,
        combat_minimum=combat_minimum,
        combat_maximum=combat_maximum,
    )
    enumerator = (
        enumerate_standard_f2p_account_states if account_mode == "f2p_standard_training" else enumerate_account_states
    )
    return list(enumerator(bounds, ruleset.mechanics, max_candidates=max_candidates))


def solve_verified_offense(
    ruleset: Ruleset,
    *,
    target: OffensiveTarget = OffensiveTarget(),
    attack_range: LevelRange = LevelRange(1, 40),
    strength_range: LevelRange = LevelRange(1, 60),
    ranged_range: LevelRange = LevelRange(1, 60),
    prayer_maximum: int = 43,
    hitpoints_range: LevelRange = LevelRange(10, 99),
    combat_minimum: int = 30,
    combat_maximum: int = 40,
    top: int = 10,
    max_candidates: int | None = None,
    account_mode: str = "f2p_standard_training",
) -> Mapping[str, object]:
    ruleset.verify_source_archive()
    ruleset.mechanics.check_required(
        (
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
            "combat_style.f2p_bonuses",
            "prayer.f2p.attack_boosts",
            "prayer.f2p.strength_boosts",
            "prayer.f2p.ranged_boosts",
            "prayer.f2p.extra_ranged_boosts",
            "prayer.pvp_protection",
            "food.swordfish",
            "food.anchovy_pizza",
            "potion.strength",
        )
    )
    if top < 1:
        raise ValueError("solve_verified_offense requires top >= 1")
    if account_mode not in {"independent_hp", "f2p_standard_training"}:
        raise ValueError(f"Unknown account mode {account_mode!r}")
    if combat_minimum < ruleset.combat_level_minimum:
        raise ValueError(f"Combat levels below {ruleset.combat_level_minimum} are outside this ruleset")
    if combat_maximum > ruleset.combat_level_maximum:
        raise ValueError(f"Combat levels above {ruleset.combat_level_maximum} are outside this ruleset")
    relevant_prayers = tuple(
        level for level in relevant_prayer_levels(ruleset.mechanics, include_magic=False) if level <= prayer_maximum
    )
    if not relevant_prayers:
        raise DataUnavailableError("No verified prayer levels remain within the requested cap")
    items = _supported_items(ruleset)
    top_overall: list[OffensiveCandidate] = []
    top_by_ko: list[OffensiveCandidate] = []
    by_hitpoints: dict[int, list[OffensiveCandidate]] = {}
    by_combat_level: dict[int, list[OffensiveCandidate]] = {}
    generated_accounts = 0
    pareto_accounts = 0
    achievable_accounts = 0
    evaluated_candidates = 0
    visited_accounts: set[str] = set()
    kit_cache: dict[tuple[int, ...], tuple[CombatKit, ...]] = {}

    archetypes = (
        (
            "melee_only",
            LevelRange(max(40, attack_range.minimum), attack_range.maximum),
            strength_range,
            LevelRange(1, 1),
        ),
        (
            "ranged_only",
            LevelRange(1, 1),
            LevelRange(1, 1),
            LevelRange(max(30, ranged_range.minimum), ranged_range.maximum),
        ),
        (
            "hybrid",
            LevelRange(max(40, attack_range.minimum), attack_range.maximum),
            strength_range,
            LevelRange(max(30, ranged_range.minimum), ranged_range.maximum),
        ),
    )
    for _, attack_bounds, strength_bounds, ranged_bounds in archetypes:
        if (
            attack_bounds.minimum > attack_bounds.maximum
            or strength_bounds.minimum > strength_bounds.maximum
            or ranged_bounds.minimum > ranged_bounds.maximum
        ):
            continue
        for prayer_level in relevant_prayers:
            accounts = _solve_bounds(
                ruleset,
                attack=attack_bounds,
                strength=strength_bounds,
                ranged=ranged_bounds,
                prayer=LevelRange(prayer_level, prayer_level),
                hitpoints=hitpoints_range,
                combat_minimum=combat_minimum,
                combat_maximum=combat_maximum,
                max_candidates=max_candidates,
                account_mode=account_mode,
            )
            new_accounts: list[AccountState] = []
            for account in accounts:
                if account.canonical_id in visited_accounts:
                    continue
                visited_accounts.add(account.canonical_id)
                generated_accounts += 1
                if account_mode == "f2p_standard_training" and not standard_f2p_hitpoints_achievable(
                    account, ruleset.mechanics
                ):
                    continue
                achievable_accounts += 1
                new_accounts.append(account)
            efficient_accounts = prune_dominated_account_states(tuple(new_accounts), items, ruleset)
            pareto_accounts += len(efficient_accounts)
            for account in efficient_accounts:
                legal_signature = tuple(item.item_id for item in items if is_item_legal(item, account))
                kits = kit_cache.get(legal_signature)
                if kits is None:
                    kits = generate_combat_kits(account, items, offense_only=True).kits
                    kit_cache[legal_signature] = kits
                if not kits:
                    continue
                for strength_potion in (False, True):
                    eligible = tuple(
                        kit
                        for kit in kits
                        if not strength_potion
                        or any(
                            _is_melee_damage(_style_damage_type(style))
                            for weapon in (kit.primary_weapon, kit.ko_weapon)
                            for style in weapon.attack_styles
                        )
                    )
                    if not eligible:
                        continue
                    reduced_kits = _prune_kits_for_report_limit(
                        eligible,
                        ruleset,
                        account,
                        target,
                        strength_potion=strength_potion,
                        limit=top,
                    )
                    for kit in reduced_kits:
                        candidate = _candidate_for_kit(ruleset, account, kit, target, strength_potion=strength_potion)
                        evaluated_candidates += 1
                        _bounded_insert(top_overall, candidate, top)
                        _bounded_insert(
                            top_by_ko,
                            candidate,
                            top,
                            key=lambda item: (
                                item.ko.profile.max_hit,
                                item.primary.profile.expected_damage_per_tick,
                                item.ko.profile.expected_damage_per_tick,
                                item.inventory.by_total_healing.total_healing,
                                item.inventory.by_total_actions.total_actions,
                            ),
                        )
                        _bounded_insert(by_hitpoints.setdefault(account.hitpoints_level, []), candidate, 1)
                        _bounded_insert(by_combat_level.setdefault(candidate.combat_level, []), candidate, 1)

    return {
        "scope": "verified_offense_frontier_v1",
        "account_mode": account_mode,
        "verification": {
            "status": "verified_for_closed_form_offense_only",
            "included_item_scope": F2P_STANDARD_WORLD_SCOPE,
            "full_duel_ranking": False,
            "catalog_complete": False,
            "verified_item_count": len(ruleset.items),
            "verified_consumable_count": len(ruleset.consumables),
            "catalog_warning": (
                "Search is exhaustive only over the promoted partial catalog; "
                "unpromoted F2P weapons and effect consumables can change rankings"
            ),
        },
        "reproducibility": dict(ruleset.reproducibility_metadata),
        "target": {
            "defence_level": target.defence_level,
            "stab_defence_bonus": target.stab_defence_bonus,
            "slash_defence_bonus": target.slash_defence_bonus,
            "crush_defence_bonus": target.crush_defence_bonus,
            "ranged_defence_bonus": target.ranged_defence_bonus,
            "protected_style": target.protected_style,
            "protection_multiplier": _fraction_document(target.protection_multiplier),
        },
        "assumptions": [
            "magic is fixed at level 1 in this melee/ranged closed-form frontier; "
            "verified spell and projectile timing data are reported separately",
            "prayer levels are compressed to verified F2P offense breakpoints because intermediate levels "
            "add combat cost without changing immediate offensive output",
            "results rank exact per-attack and per-tick offensive output, not full duel win probability",
            "prayer drain, PID reassignment, movement, weapon-switch timing, and defensive prayer usage "
            "remain outside this command's objective",
            "the promoted item/consumable catalog is partial, so this artifact is not an exhaustive F2P build ranking",
        ],
        "search": {
            "generated_accounts": generated_accounts,
            "achievable_accounts": achievable_accounts,
            "unachievable_accounts_rejected": generated_accounts - achievable_accounts,
            "pareto_accounts": pareto_accounts,
            "dominated_accounts_pruned": achievable_accounts - pareto_accounts,
            "evaluated_candidates": evaluated_candidates,
            "top_limit": top,
            "prayer_levels_considered": list(relevant_prayers),
            "cache_sizes": dict(frontier_cache_sizes()),
        },
        "top_overall": [candidate.to_document() for candidate in top_overall],
        "top_by_ko_max_hit": [candidate.to_document() for candidate in top_by_ko],
        "best_by_hitpoints": {
            str(hitpoints): candidates[0].to_document() for hitpoints, candidates in sorted(by_hitpoints.items())
        },
        "best_by_combat_level": {
            str(combat_level): candidates[0].to_document()
            for combat_level, candidates in sorted(by_combat_level.items())
        },
    }
