"""Attach equipment to exact account profiles, caching gear by unlock signature.

Accounts that can equip the same set of verified items share one gear
expansion. Two kit modes are supported:

* ``full`` – every retained armour/weapon combination (the legacy matrix rule).
* ``offence_pareto`` – per weapon, keep armour that is Pareto-optimal in the
  offensive bonuses that weapon can use; every other slot is filled with the
  best-defence option. This is the compact tier-1 kit used to compare skill
  combinations on equal footing before the winners get a full gear expansion.

Ported to Rust as ``pure_math/src/gear_matrix.rs`` (together with the row builder in
:mod:`pure_solver.gear_matrix`); this module is the golden reference.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import product

from .account_frontier import account_levels, equipment_unlock_signature
from .accounts import AccountState
from .dominance import prune_dominated_items
from .gear_matrix import (
    MATRIX_ARMOUR_SLOTS,
    GearMatrixProfile,
    VerifiedGearMatrix,
    _best_compatible_ammo,
    _build_combination,
)
from .legality import EquipmentItem

KIT_MODES = ("full", "offence_pareto")
_MELEE_DAMAGE_TYPES = ("stab", "slash", "crush")
_DEFENCE_BONUSES = ("defence_stab", "defence_slash", "defence_crush", "defence_ranged", "defence_magic")


@dataclass(frozen=True)
class SignatureGear:
    """Weapon-keyed item tuples shared by every account with one unlock signature."""

    slot_options: Mapping[str, tuple[EquipmentItem, ...]]
    weapon_options: tuple[EquipmentItem, ...]
    ammo_by_weapon_id: Mapping[int, EquipmentItem]
    shield_by_weapon_id: Mapping[int, EquipmentItem]
    row_items: tuple[tuple[EquipmentItem, ...], ...]


def _offence_bonus_names(weapon: EquipmentItem) -> tuple[str, ...]:
    damage_types = {style.rpartition("_")[2] for style in weapon.attack_styles}
    if "ranged" in damage_types:
        return ("attack_ranged", "ranged_strength")
    melee = tuple(f"attack_{kind}" for kind in _MELEE_DAMAGE_TYPES if kind in damage_types)
    return (*melee, "melee_strength")


def _offence_vector(item: EquipmentItem, names: Sequence[str]) -> tuple[int, ...]:
    return tuple(item.bonuses.get(name, 0) for name in names)


def _defence_key(item: EquipmentItem) -> tuple[int, int]:
    return (sum(item.bonuses.get(name, 0) for name in _DEFENCE_BONUSES), item.bonuses.get("prayer", 0))


def _offence_pareto_items(items: Sequence[EquipmentItem], names: Sequence[str]) -> tuple[EquipmentItem, ...]:
    """Items whose offence vector nobody matches-or-beats; ties resolved by defence."""
    best_by_vector: dict[tuple[int, ...], EquipmentItem] = {}
    for item in items:
        vector = _offence_vector(item, names)
        current = best_by_vector.get(vector)
        if current is None or (_defence_key(item), -item.item_id) > (_defence_key(current), -current.item_id):
            best_by_vector[vector] = item
    vectors = list(best_by_vector)
    return tuple(
        best_by_vector[vector]
        for vector in vectors
        if not any(other != vector and all(o >= v for o, v in zip(other, vector)) for other in vectors)
    )


def _slot_options(retained: Iterable[EquipmentItem]) -> dict[str, tuple[EquipmentItem, ...]]:
    relevant = [item for item in retained if item.slot in {*MATRIX_ARMOUR_SLOTS, "weapon", "2h", "ammo", "shield"}]
    return {
        slot: tuple(item for item in relevant if item.slot == slot)
        for slot in (*MATRIX_ARMOUR_SLOTS, "weapon", "2h", "ammo", "shield")
    }


def _row_items_for_weapon(
    weapon: EquipmentItem,
    armour_choices: Sequence[Sequence[EquipmentItem]],
    ammo: EquipmentItem | None,
    shield: EquipmentItem | None,
) -> Iterator[tuple[EquipmentItem, ...]]:
    extras = (*((ammo,) if ammo else ()), *((shield,) if shield else ()))
    for armour in product(*armour_choices):
        yield (*armour, weapon, *extras)


def _armour_choices(
    slot_options: Mapping[str, tuple[EquipmentItem, ...]],
    weapon: EquipmentItem,
    kit_mode: str,
) -> tuple[tuple[EquipmentItem, ...], ...]:
    if kit_mode == "full":
        return tuple(slot_options[slot] for slot in MATRIX_ARMOUR_SLOTS)
    names = _offence_bonus_names(weapon)
    return tuple(_offence_pareto_items(slot_options[slot], names) for slot in MATRIX_ARMOUR_SLOTS)


def build_signature_gear(
    account: AccountState,
    items: Sequence[EquipmentItem],
    *,
    kit_mode: str,
) -> SignatureGear:
    if kit_mode not in KIT_MODES:
        raise ValueError(f"Unknown kit mode {kit_mode!r}; expected one of {KIT_MODES}")
    retained = tuple(prune_dominated_items(account, items).retained)
    options = _slot_options(retained)
    weapons = (*options["weapon"], *options["2h"])
    shield = next((item for item in options["shield"] if item.name == "Mooleta"), None)
    ammo_by_weapon = {
        weapon.item_id: ammo
        for weapon in weapons
        if weapon.ammo_ids and (ammo := _best_compatible_ammo(weapon, options["ammo"])) is not None
    }
    shield_by_weapon = {weapon.item_id: shield for weapon in weapons if weapon.slot == "weapon" and shield}
    rows = tuple(
        row
        for weapon in weapons
        for row in _row_items_for_weapon(
            weapon,
            _armour_choices(options, weapon, kit_mode),
            ammo_by_weapon.get(weapon.item_id),
            shield_by_weapon.get(weapon.item_id),
        )
    )
    return SignatureGear(
        {slot: options[slot] for slot in MATRIX_ARMOUR_SLOTS}, weapons, ammo_by_weapon, shield_by_weapon, rows
    )


def _profile_for_account(profile_id: int, account: AccountState, gear: SignatureGear) -> GearMatrixProfile:
    levels = {
        "attack": account.attack_level,
        "strength": account.strength_level,
        "ranged": account.ranged_level,
        "magic": account.magic_level,
        "prayer": account.prayer_level,
    }
    combinations = tuple(
        _build_combination(
            profile_id=profile_id, account=account, level_minimums=levels, level_maximums=levels, items=row
        )
        for row in gear.row_items
    )
    return GearMatrixProfile(
        profile_id=profile_id,
        account=account,
        level_minimums=levels,
        level_maximums=levels,
        slot_options=gear.slot_options,
        weapon_options=gear.weapon_options,
        compatible_ammo_by_weapon_id=gear.ammo_by_weapon_id,
        shield_name_by_weapon_id={
            w.item_id: (gear.shield_by_weapon_id[w.item_id].name if w.item_id in gear.shield_by_weapon_id else "EMPTY")
            for w in gear.weapon_options
        },
        combinations=combinations,
    )


def build_account_gear_matrix(
    accounts: Sequence[AccountState],
    items: Iterable[EquipmentItem],
    *,
    kit_mode: str = "offence_pareto",
) -> tuple[VerifiedGearMatrix, int]:
    """Expand accounts into loadout rows; returns the matrix and the signature count."""
    item_tuple = tuple(items)
    gear_by_signature: dict[frozenset[int], SignatureGear] = {}
    profiles: list[GearMatrixProfile] = []
    for profile_id, account in enumerate(accounts, start=1):
        signature = equipment_unlock_signature(account, item_tuple)
        if signature not in gear_by_signature:
            gear_by_signature[signature] = build_signature_gear(account, item_tuple, kit_mode=kit_mode)
        profiles.append(_profile_for_account(profile_id, account, gear_by_signature[signature]))
    matrix = VerifiedGearMatrix(
        maximum_level=max(max(account_levels(account)) for account in accounts) if accounts else 0,
        profile_count=len(profiles),
        combination_count=sum(len(profile.combinations) for profile in profiles),
        profiles=tuple(profiles),
    )
    return matrix, len(gear_by_signature)
