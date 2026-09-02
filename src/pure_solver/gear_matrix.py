"""Verified gear matrix: enumerate head/neck/body/legs/hands/weapon combinations (with derived ammo and shield)
per level band or per exact account, and write them as JSON and CSV.

The row builder and CSV layout are ported to Rust in ``pure_math/src/gear_matrix.rs``; this module is the
golden reference.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path
from typing import Any

from .accounts import AccountSearchBounds, AccountState, enumerate_account_states
from .dominance import prune_dominated_items
from .experience import enumerate_standard_f2p_account_states
from .gear_catalog_export import BONUS_COLUMNS, REQUIREMENT_COLUMNS, LevelItemProfile, verified_level_item_profiles
from .legality import EquipmentItem
from .mechanics import MechanicRegistry

MATRIX_ARMOUR_SLOTS = ("head", "neck", "body", "legs", "hands")
MATRIX_SKILLS = ("attack", "strength", "ranged", "magic", "prayer")
_EMPTY_NAME = "EMPTY"


@dataclass(frozen=True)
class GearMatrixCombination:
    profile_id: int
    account: AccountState
    level_minimums: Mapping[str, int]
    level_maximums: Mapping[str, int]
    item_ids: Mapping[str, int | None]
    item_names: Mapping[str, str]
    requirements: Mapping[str, int]
    bonuses: Mapping[str, int]
    weapon_slot: str
    weapon_type: str | None
    weapon_attack_speed: int | None
    weapon_attack_range: int | None
    weapon_attack_styles: tuple[str, ...]
    two_handed: bool


@dataclass(frozen=True)
class GearMatrixProfile:
    profile_id: int
    account: AccountState
    level_minimums: Mapping[str, int]
    level_maximums: Mapping[str, int]
    slot_options: Mapping[str, tuple[EquipmentItem, ...]]
    weapon_options: tuple[EquipmentItem, ...]
    compatible_ammo_by_weapon_id: Mapping[int, EquipmentItem]
    shield_name_by_weapon_id: Mapping[int, str]
    combinations: tuple[GearMatrixCombination, ...]


@dataclass(frozen=True)
class VerifiedGearMatrix:
    maximum_level: int
    profile_count: int
    combination_count: int
    profiles: tuple[GearMatrixProfile, ...]

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "purpose": "verified_f2p_equipment_slot_matrix",
            "maximum_level": self.maximum_level,
            "profile_count": self.profile_count,
            "combination_count": self.combination_count,
            "slot_scope": {
                "variable_slots": [*MATRIX_ARMOUR_SLOTS, "weapon"],
                "derived_slots": ["ammo", "shield"],
                "ignored_slots": ["cape", "feet", "ring"],
            },
            "profiles": [
                {
                    "profile_id": profile.profile_id,
                    "account": _account_document(profile.account),
                    "level_minimums": dict(profile.level_minimums),
                    "level_maximums": dict(profile.level_maximums),
                    "slot_option_ids": {
                        slot: [item.item_id for item in profile.slot_options.get(slot, ())]
                        for slot in MATRIX_ARMOUR_SLOTS
                    },
                    "weapon_option_ids": [item.item_id for item in profile.weapon_options],
                    "compatible_ammo_by_weapon_id": {
                        str(weapon_id): ammo.item_id
                        for weapon_id, ammo in sorted(profile.compatible_ammo_by_weapon_id.items())
                    },
                    "shield_name_by_weapon_id": dict(sorted(profile.shield_name_by_weapon_id.items())),
                    "combination_count": len(profile.combinations),
                }
                for profile in self.profiles
            ],
            "combinations": [asdict(row) for profile in self.profiles for row in profile.combinations],
        }


def build_verified_gear_matrix(
    items: Iterable[EquipmentItem],
    *,
    maximum_level: int = 40,
) -> VerifiedGearMatrix:
    profiles = verified_level_item_profiles(items, maximum_level=maximum_level)
    matrix_profiles = tuple(_build_profile(profile) for profile in profiles)
    return VerifiedGearMatrix(
        maximum_level=maximum_level,
        profile_count=len(matrix_profiles),
        combination_count=sum(len(profile.combinations) for profile in matrix_profiles),
        profiles=matrix_profiles,
    )


def build_exact_account_gear_matrix(
    items: Iterable[EquipmentItem],
    mechanics: MechanicRegistry,
    bounds: AccountSearchBounds,
    *,
    max_candidates: int | None = None,
    account_mode: str = "f2p_standard_training",
) -> VerifiedGearMatrix:
    """Build an exact-account matrix instead of unlock-band representatives."""

    if account_mode not in {"independent_hp", "f2p_standard_training"}:
        raise ValueError(f"Unknown account mode {account_mode!r}")
    item_tuple = tuple(items)
    enumerator = (
        enumerate_standard_f2p_account_states if account_mode == "f2p_standard_training" else enumerate_account_states
    )
    matrix_profiles = tuple(
        _build_exact_profile(profile_id, account, item_tuple)
        for profile_id, account in enumerate(
            enumerator(bounds, mechanics, max_candidates=max_candidates),
            start=1,
        )
    )
    maximum_level = max(
        bounds.attack.maximum,
        bounds.strength.maximum,
        bounds.ranged.maximum,
        bounds.magic.maximum,
        bounds.prayer.maximum,
        bounds.hitpoints.maximum,
    )
    return VerifiedGearMatrix(
        maximum_level=maximum_level,
        profile_count=len(matrix_profiles),
        combination_count=sum(len(profile.combinations) for profile in matrix_profiles),
        profiles=matrix_profiles,
    )


def write_verified_gear_matrix_json(matrix: VerifiedGearMatrix, output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(matrix.to_document(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_verified_gear_matrix_csv(matrix: VerifiedGearMatrix, output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "profile_id",
        *(column for skill in MATRIX_SKILLS for column in (f"{skill}_min", f"{skill}_max")),
        "defence",
        "hitpoints",
        *(f"account_{skill}" for skill in (*MATRIX_SKILLS, "defence", "hitpoints")),
        "head_id",
        "head_name",
        "neck_id",
        "neck_name",
        "body_id",
        "body_name",
        "legs_id",
        "legs_name",
        "hands_id",
        "hands_name",
        "weapon_id",
        "weapon_name",
        "weapon_slot",
        "ammo_id",
        "ammo_name",
        "shield_id",
        "shield_name",
        *(f"req_{skill}" for skill in REQUIREMENT_COLUMNS),
        *BONUS_COLUMNS,
        "weapon_type",
        "weapon_attack_speed",
        "weapon_attack_range",
        "weapon_attack_styles",
        "two_handed",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for profile in matrix.profiles:
            for row in profile.combinations:
                band_columns = {
                    column: value
                    for skill in MATRIX_SKILLS
                    for column, value in (
                        (f"{skill}_min", row.level_minimums[skill]),
                        (f"{skill}_max", row.level_maximums[skill]),
                    )
                }
                writer.writerow(
                    {
                        "profile_id": row.profile_id,
                        **band_columns,
                        "defence": 1,
                        "hitpoints": row.account.hitpoints_level,
                        **{
                            f"account_{skill}": getattr(row.account, f"{skill}_level")
                            for skill in (*MATRIX_SKILLS, "defence", "hitpoints")
                        },
                        **_slot_csv_columns("head", row),
                        **_slot_csv_columns("neck", row),
                        **_slot_csv_columns("body", row),
                        **_slot_csv_columns("legs", row),
                        **_slot_csv_columns("hands", row),
                        **_slot_csv_columns("weapon", row),
                        "weapon_slot": row.weapon_slot,
                        **_slot_csv_columns("ammo", row),
                        **_slot_csv_columns("shield", row),
                        **{f"req_{skill}": row.requirements.get(skill, 0) for skill in REQUIREMENT_COLUMNS},
                        **{bonus: row.bonuses.get(bonus, 0) for bonus in BONUS_COLUMNS},
                        "weapon_type": row.weapon_type,
                        "weapon_attack_speed": row.weapon_attack_speed,
                        "weapon_attack_range": row.weapon_attack_range,
                        "weapon_attack_styles": ";".join(row.weapon_attack_styles),
                        "two_handed": row.two_handed,
                    }
                )


def _build_profile(profile: LevelItemProfile) -> GearMatrixProfile:
    account = AccountState(
        profile.level_minimums["attack"],
        profile.level_minimums["strength"],
        profile.level_minimums["ranged"],
        profile.level_minimums["magic"],
        profile.level_minimums["prayer"],
        10,
    )
    return _build_matrix_profile(
        profile_id=profile.profile_id,
        account=account,
        level_minimums=profile.level_minimums,
        level_maximums=profile.level_maximums,
        retained_items=profile.retained_items,
    )


def _build_exact_profile(
    profile_id: int,
    account: AccountState,
    items: tuple[EquipmentItem, ...],
) -> GearMatrixProfile:
    exact_levels = {
        "attack": account.attack_level,
        "strength": account.strength_level,
        "ranged": account.ranged_level,
        "magic": account.magic_level,
        "prayer": account.prayer_level,
    }
    retained_items = prune_dominated_items(account, items).retained
    return _build_matrix_profile(
        profile_id=profile_id,
        account=account,
        level_minimums=exact_levels,
        level_maximums=exact_levels,
        retained_items=retained_items,
    )


def _build_matrix_profile(
    *,
    profile_id: int,
    account: AccountState,
    level_minimums: Mapping[str, int],
    level_maximums: Mapping[str, int],
    retained_items: Iterable[EquipmentItem],
) -> GearMatrixProfile:
    relevant = [
        item for item in retained_items if item.slot in {*MATRIX_ARMOUR_SLOTS, "weapon", "2h", "ammo", "shield"}
    ]
    slot_options = {slot: tuple(item for item in relevant if item.slot == slot) for slot in MATRIX_ARMOUR_SLOTS}
    weapon_options = tuple(item for item in relevant if item.slot in {"weapon", "2h"})
    ammo_options = tuple(item for item in relevant if item.slot == "ammo")
    shields = tuple(item for item in relevant if item.slot == "shield")
    mooleta = next((item for item in shields if item.name == "Mooleta"), None)
    best_ammo_by_weapon_id = {
        weapon.item_id: _best_compatible_ammo(weapon, ammo_options) for weapon in weapon_options if weapon.ammo_ids
    }
    combinations = []
    for armour_items in product(*(slot_options[slot] for slot in MATRIX_ARMOUR_SLOTS)):
        for weapon in weapon_options:
            ammo = best_ammo_by_weapon_id.get(weapon.item_id)
            shield_item = mooleta if weapon.slot == "weapon" else None
            row_items = (
                *armour_items,
                weapon,
                *((ammo,) if ammo is not None else ()),
                *((shield_item,) if shield_item is not None else ()),
            )
            combinations.append(
                _build_combination(
                    profile_id=profile_id,
                    account=account,
                    level_minimums=level_minimums,
                    level_maximums=level_maximums,
                    items=row_items,
                )
            )
    return GearMatrixProfile(
        profile_id=profile_id,
        account=account,
        level_minimums=level_minimums,
        level_maximums=level_maximums,
        slot_options=slot_options,
        weapon_options=weapon_options,
        compatible_ammo_by_weapon_id={
            weapon_id: ammo for weapon_id, ammo in best_ammo_by_weapon_id.items() if ammo is not None
        },
        shield_name_by_weapon_id={
            weapon.item_id: (mooleta.name if weapon.slot == "weapon" and mooleta is not None else _EMPTY_NAME)
            for weapon in weapon_options
        },
        combinations=tuple(combinations),
    )


def _build_combination(
    *,
    profile_id: int,
    account: AccountState,
    level_minimums: Mapping[str, int],
    level_maximums: Mapping[str, int],
    items: tuple[EquipmentItem, ...],
) -> GearMatrixCombination:
    by_slot = {item.slot if item.slot != "2h" else "weapon": item for item in items}
    aggregate_requirements: dict[str, int] = {}
    aggregate_bonuses = {bonus: 0 for bonus in BONUS_COLUMNS}
    for item in items:
        for skill, level in item.requirements.items():
            aggregate_requirements[skill] = max(aggregate_requirements.get(skill, 0), level)
        for bonus in BONUS_COLUMNS:
            aggregate_bonuses[bonus] += item.bonuses.get(bonus, 0)
    weapon = next(item for item in items if item.slot in {"weapon", "2h"})
    ammo = next((item for item in items if item.slot == "ammo"), None)
    shield = next((item for item in items if item.slot == "shield"), None)
    return GearMatrixCombination(
        profile_id=profile_id,
        account=account,
        level_minimums=dict(level_minimums),
        level_maximums=dict(level_maximums),
        item_ids={slot: by_slot[slot].item_id if slot in by_slot else None for slot in (*MATRIX_ARMOUR_SLOTS, "weapon")}
        | {
            "ammo": ammo.item_id if ammo is not None else None,
            "shield": shield.item_id if shield is not None else None,
        },
        item_names={
            slot: by_slot[slot].name if slot in by_slot else _EMPTY_NAME for slot in (*MATRIX_ARMOUR_SLOTS, "weapon")
        }
        | {
            "ammo": ammo.name if ammo is not None else _EMPTY_NAME,
            "shield": shield.name if shield is not None else _EMPTY_NAME,
        },
        requirements=aggregate_requirements,
        bonuses=aggregate_bonuses,
        weapon_slot=weapon.slot,
        weapon_type=weapon.weapon_type,
        weapon_attack_speed=weapon.attack_speed,
        weapon_attack_range=weapon.attack_range,
        weapon_attack_styles=weapon.attack_styles,
        two_handed=weapon.two_handed,
    )


def _best_compatible_ammo(
    weapon: EquipmentItem,
    ammo_options: Iterable[EquipmentItem],
) -> EquipmentItem | None:
    compatible = [item for item in ammo_options if item.item_id in weapon.ammo_ids]
    if not compatible:
        return None
    return max(
        compatible,
        key=lambda item: (
            item.bonuses.get("ranged_strength", 0),
            item.bonuses.get("attack_ranged", 0),
            -item.item_id,
        ),
    )


def _slot_csv_columns(slot: str, row: GearMatrixCombination) -> dict[str, object]:
    return {
        f"{slot}_id": row.item_ids.get(slot),
        f"{slot}_name": row.item_names.get(slot, _EMPTY_NAME),
    }


def _account_document(account: AccountState) -> dict[str, int]:
    return {
        "attack": account.attack_level,
        "strength": account.strength_level,
        "ranged": account.ranged_level,
        "magic": account.magic_level,
        "prayer": account.prayer_level,
        "defence": account.defence_level,
        "hitpoints": account.hitpoints_level,
    }
