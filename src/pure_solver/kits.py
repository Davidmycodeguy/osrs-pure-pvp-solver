"""Combat kits for one account: prune dominated items, build Pareto-pruned worn loadouts, pair a primary loadout
with a KO-switch loadout, and count the inventory slots the switch costs.

The Rust Stage 5 kit expansion (``pure_math/src/kits/``) borrows the switch-slot rule from
``CombatKit.inventory_slots`` but is not a port of this module.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import product

from .accounts import AccountState
from .canonical import canonical_hash
from .dominance import DominanceResult, prune_dominated_items
from .inventory import InventoryState
from .legality import EquipmentItem, LegalityContext, Loadout, is_loadout_legal, legal_loadouts

_LOADOUT_SLOT_ORDER = (
    "head",
    "cape",
    "neck",
    "ammo",
    "weapon",
    "2h",
    "body",
    "shield",
    "legs",
    "hands",
    "feet",
    "ring",
)
_COMMON_WORN_SLOTS = ("head", "cape", "neck", "body", "legs", "hands", "feet", "ring")
_COMBAT_CONFIGURATION_SLOTS = ("ammo", "weapon", "2h", "shield")
_OFFENSIVE_BONUS_KEYS = (
    "attack_stab",
    "attack_slash",
    "attack_crush",
    "attack_magic",
    "attack_ranged",
    "melee_strength",
    "magic_damage",
    "ranged_strength",
)


def _loadout_weapon(loadout: Loadout) -> EquipmentItem | None:
    return loadout.item_in_slot("weapon") or loadout.item_in_slot("2h")


def _loadout_ammunition(loadout: Loadout) -> EquipmentItem | None:
    return loadout.item_in_slot("ammo")


def _weapon_requires_ammunition(weapon: EquipmentItem) -> bool:
    return bool(weapon.ammo_ids)


def _aggregate_bonuses(loadout: Loadout) -> Mapping[str, int]:
    totals: dict[str, int] = {}
    for item in loadout.items:
        for bonus, value in item.bonuses.items():
            totals[bonus] = totals.get(bonus, 0) + value
    return totals


def _switch_slots(active: Loadout, alternate: Loadout) -> int:
    active_ids = {item.item_id for item in active.items}
    return sum(1 for item in alternate.items if item.item_id not in active_ids)


def _merge_loadouts(*loadouts: Loadout) -> Loadout:
    merged: dict[str, EquipmentItem] = {}
    for loadout in loadouts:
        for item in loadout.items:
            merged[item.slot] = item
    return Loadout(tuple(merged[slot] for slot in _LOADOUT_SLOT_ORDER if slot in merged))


def _prune_loadouts(
    loadouts: Iterable[Loadout],
    *,
    bonus_keys: tuple[str, ...] | None = None,
) -> tuple[Loadout, ...]:
    """Pareto-prune equivalent worn states without collapsing trade-offs."""
    candidates = tuple(loadouts)
    if bonus_keys is None:
        bonus_keys = tuple(sorted({key for loadout in candidates for item in loadout.items for key in item.bonuses}))
    signatures = {
        loadout.canonical_id: tuple(
            (-_aggregate_bonuses(loadout).get(key, 0) if key == "weight" else _aggregate_bonuses(loadout).get(key, 0))
            for key in bonus_keys
        )
        for loadout in candidates
    }
    retained: list[Loadout] = []
    for candidate in candidates:
        right = signatures[candidate.canonical_id]
        dominated = False
        for other in candidates:
            if other.canonical_id == candidate.canonical_id:
                continue
            left = signatures[other.canonical_id]
            weakly_better = all(a >= b for a, b in zip(left, right))
            strictly_better = any(a > b for a, b in zip(left, right))
            equivalent_preferred = left == right and other.canonical_id < candidate.canonical_id
            if weakly_better and (strictly_better or equivalent_preferred):
                dominated = True
                break
        if not dominated:
            retained.append(candidate)
    return tuple(sorted(retained, key=lambda loadout: loadout.canonical_id))


@dataclass(frozen=True)
class CombatKit:
    primary_loadout: Loadout
    ko_loadout: Loadout

    @property
    def canonical_id(self) -> str:
        return canonical_hash(
            {
                "primary_loadout": sorted(item.item_id for item in self.primary_loadout.items),
                "ko_loadout": sorted(item.item_id for item in self.ko_loadout.items),
            }
        )

    @property
    def primary_weapon(self) -> EquipmentItem:
        weapon = _loadout_weapon(self.primary_loadout)
        if weapon is None:
            raise ValueError("Combat kit primary loadout has no weapon")
        return weapon

    @property
    def ko_weapon(self) -> EquipmentItem:
        weapon = _loadout_weapon(self.ko_loadout)
        if weapon is None:
            raise ValueError("Combat kit KO loadout has no weapon")
        return weapon

    @property
    def primary_ammunition(self) -> EquipmentItem | None:
        return _loadout_ammunition(self.primary_loadout)

    @property
    def ko_ammunition(self) -> EquipmentItem | None:
        return _loadout_ammunition(self.ko_loadout)

    @property
    def ammunition(self) -> EquipmentItem | None:
        return self.primary_ammunition or self.ko_ammunition

    @property
    def common_worn_items(self) -> tuple[EquipmentItem, ...]:
        ko_ids = {item.item_id for item in self.ko_loadout.items}
        return tuple(item for item in self.primary_loadout.items if item.item_id in ko_ids)

    def equipped_bonuses(self, purpose: str) -> Mapping[str, int]:
        if purpose == "primary":
            return _aggregate_bonuses(self.primary_loadout)
        if purpose == "ko":
            return _aggregate_bonuses(self.ko_loadout)
        raise ValueError(f"Unknown combat kit purpose {purpose!r}")

    @property
    def inventory_slots(self) -> int:
        return max(
            _switch_slots(self.primary_loadout, self.ko_loadout),
            _switch_slots(self.ko_loadout, self.primary_loadout),
        )

    def available_inventory_slots(self, capacity: int) -> int:
        if capacity < self.inventory_slots:
            raise ValueError("Combat kit exceeds inventory capacity")
        return capacity - self.inventory_slots


@dataclass(frozen=True)
class CombatKitSearch:
    kits: tuple[CombatKit, ...]
    item_dominance: DominanceResult


def inventory_fits_combat_kit(inventory: InventoryState, kit: CombatKit) -> bool:
    """Account for carried switch pieces against the configured inventory cap."""
    return inventory.occupied_slots + kit.inventory_slots <= inventory.capacity


def is_combat_kit_legal(
    kit: CombatKit,
    account: AccountState,
    context: LegalityContext = LegalityContext(),
) -> bool:
    primary_without_ammo = Loadout(tuple(item for item in kit.primary_loadout.items if item.slot != "ammo"))
    ko_without_ammo = Loadout(tuple(item for item in kit.ko_loadout.items if item.slot != "ammo"))
    if not is_loadout_legal(primary_without_ammo, account, context):
        return False
    if not is_loadout_legal(ko_without_ammo, account, context):
        return False
    primary_weapon = _loadout_weapon(kit.primary_loadout)
    if primary_weapon is None:
        return False
    if _weapon_requires_ammunition(primary_weapon) and _loadout_ammunition(kit.primary_loadout) is None:
        return False
    if _weapon_requires_ammunition(primary_weapon) and (
        _loadout_ammunition(kit.primary_loadout).item_id not in primary_weapon.ammo_ids
    ):
        return False
    ko_weapon = _loadout_weapon(kit.ko_loadout)
    if ko_weapon is None:
        return False
    if _weapon_requires_ammunition(ko_weapon) and _loadout_ammunition(kit.ko_loadout) is None:
        return False
    if _weapon_requires_ammunition(ko_weapon) and (
        _loadout_ammunition(kit.ko_loadout).item_id not in ko_weapon.ammo_ids
    ):
        return False
    return True


def generate_combat_kits(
    account: AccountState,
    items: Iterable[EquipmentItem],
    *,
    context: LegalityContext = LegalityContext(),
    offense_only: bool = False,
) -> CombatKitSearch:
    dominance = prune_dominated_items(account, items, context=context)
    retained = dominance.retained
    present_slots = {item.slot for item in retained}
    common_slots = tuple(slot for slot in _COMMON_WORN_SLOTS if slot in present_slots)
    common_loadouts = tuple(
        loadout for loadout in legal_loadouts(account, retained, common_slots, prune_dominated=False, context=context)
    )
    common_loadouts = _prune_loadouts(
        common_loadouts,
        bonus_keys=_OFFENSIVE_BONUS_KEYS if offense_only else None,
    )
    configuration_slots = tuple(slot for slot in _COMBAT_CONFIGURATION_SLOTS if slot in present_slots)
    configurations = tuple(
        loadout
        for loadout in legal_loadouts(account, retained, configuration_slots, prune_dominated=False, context=context)
        if _loadout_weapon(loadout) is not None
    )
    kits: dict[str, CombatKit] = {}
    for common_loadout in common_loadouts:
        for primary_configuration, ko_configuration in product(configurations, repeat=2):
            primary_ammo = _loadout_ammunition(primary_configuration)
            ko_ammo = _loadout_ammunition(ko_configuration)
            # Ammunition remains equipped when switching to a melee weapon. If
            # only one side needs ammo, keep that stack in both loadouts so it
            # does not falsely consume an inventory switch slot.
            if primary_ammo is not None and ko_ammo is None:
                ko_configuration = Loadout((*ko_configuration.items, primary_ammo))
            elif ko_ammo is not None and primary_ammo is None:
                primary_configuration = Loadout((*primary_configuration.items, ko_ammo))
            kit = CombatKit(
                _merge_loadouts(common_loadout, primary_configuration),
                _merge_loadouts(common_loadout, ko_configuration),
            )
            if is_combat_kit_legal(kit, account, context):
                kits[kit.canonical_id] = kit
    return CombatKitSearch(
        tuple(
            sorted(
                kits.values(),
                key=lambda kit: (
                    kit.primary_weapon.item_id,
                    tuple(item.item_id for item in kit.primary_loadout.items),
                    kit.ko_weapon.item_id,
                    tuple(item.item_id for item in kit.ko_loadout.items),
                ),
            )
        ),
        dominance,
    )
