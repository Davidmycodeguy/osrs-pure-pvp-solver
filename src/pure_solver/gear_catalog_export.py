"""Account-local gear export: collapse Wiki-observed exact equivalents after legality, run verified dominance
pruning, and write the JSON/CSV caches plus the 1-Defence level-band item profiles that the band gear matrix
builds on.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path
from typing import Any

from .accounts import AccountState
from .catalog import EquipmentCatalog, ObservedCatalogItem
from .dominance import prune_dominated_items
from .legality import EquipmentItem

REQUIREMENT_COLUMNS = (
    "attack",
    "strength",
    "ranged",
    "magic",
    "prayer",
    "defence",
    "hitpoints",
)
BONUS_COLUMNS = (
    "attack_stab",
    "attack_slash",
    "attack_crush",
    "attack_magic",
    "attack_ranged",
    "defence_stab",
    "defence_slash",
    "defence_crush",
    "defence_magic",
    "defence_ranged",
    "melee_strength",
    "ranged_strength",
    "magic_damage",
    "prayer",
)


@dataclass(frozen=True)
class ObservedGearRepresentative:
    """One exact observed mechanic/stat signature legal for a specific account.

    These records are a completeness/audit cache, not solver-ready equipment.
    Strict dominance is deliberately reserved for verified EquipmentItem records,
    whose quest, availability, attack-style, ammunition, and special-mechanic
    fields have been reviewed.
    """

    representative_item_id: int
    representative_name: str
    slot: str
    requirements: Mapping[str, int]
    bonuses: Mapping[str, int]
    attack_speed: int | None
    attack_range: int | None
    combat_style: str | None
    exact_variant_item_ids: tuple[int, ...]
    exact_variant_names: tuple[str, ...]
    source_urls: tuple[str, ...]
    verification_gaps: tuple[str, ...]
    covered_by_verified_item_ids: tuple[int, ...]

    @property
    def exact_variant_count(self) -> int:
        return len(self.exact_variant_item_ids)

    @property
    def solver_eligible(self) -> bool:
        return self.representative_item_id in self.covered_by_verified_item_ids


@dataclass(frozen=True)
class LevelItemProfile:
    profile_id: int
    level_minimums: Mapping[str, int]
    level_maximums: Mapping[str, int]
    retained_items: tuple[EquipmentItem, ...]


def _level_bands(items: Iterable[EquipmentItem], skill: str, maximum: int) -> tuple[tuple[int, int], ...]:
    starts = sorted(
        {
            1,
            *(
                int(item.requirements[skill])
                for item in items
                if skill in item.requirements and 1 <= int(item.requirements[skill]) <= maximum
            ),
        }
    )
    return tuple(
        (start, starts[index + 1] - 1 if index + 1 < len(starts) else maximum) for index, start in enumerate(starts)
    )


def verified_level_item_profiles(
    items: Iterable[EquipmentItem],
    *,
    maximum_level: int = 40,
) -> tuple[LevelItemProfile, ...]:
    """Return every distinct 1-Defence item-unlock band up to a level cap.

    A profile describes an interval, not one arbitrary level. Item legality and
    account-local item dominance are constant everywhere inside that interval.
    Combat-level and HP feasibility are intentionally handled later by account
    enumeration; this export answers only the level-gate-to-item question.
    """

    if not 1 <= maximum_level <= 99:
        raise ValueError("maximum_level must be between 1 and 99")
    item_tuple = tuple(items)
    skills = ("attack", "strength", "ranged", "magic", "prayer")
    bands_by_skill = {skill: _level_bands(item_tuple, skill, maximum_level) for skill in skills}
    profiles: list[LevelItemProfile] = []
    for profile_id, bands in enumerate(product(*(bands_by_skill[skill] for skill in skills)), start=1):
        minimums = {skill: band[0] for skill, band in zip(skills, bands)}
        maximums = {skill: band[1] for skill, band in zip(skills, bands)}
        account = AccountState(
            minimums["attack"],
            minimums["strength"],
            minimums["ranged"],
            minimums["magic"],
            minimums["prayer"],
            10,
        )
        retained = prune_dominated_items(account, item_tuple).retained
        profiles.append(
            LevelItemProfile(
                profile_id=profile_id,
                level_minimums=minimums,
                level_maximums=maximums,
                retained_items=retained,
            )
        )
    return tuple(profiles)


def _requirements_met(item: ObservedCatalogItem, account: AccountState) -> bool:
    levels = {
        "attack": account.attack_level,
        "strength": account.strength_level,
        "ranged": account.ranged_level,
        "magic": account.magic_level,
        "prayer": account.prayer_level,
        "defence": account.defence_level,
        "hitpoints": account.hitpoints_level,
    }
    return all(levels.get(skill, -1) >= level for skill, level in item.requirements.items())


def _standard_f2p_observation(item: ObservedCatalogItem) -> bool:
    observation = item.observation
    return (
        observation.free_to_play
        and not observation.members
        and observation.equipable
        and observation.environment_scope is None
        and "last man standing" not in item.source_title.casefold()
        and "deadman" not in item.source_title.casefold()
    )


def _representative_key(item: ObservedCatalogItem, verified_ids: set[int]) -> tuple[object, ...]:
    # Prefer an already verified record, then an undecorated/base name, then a
    # stable low ID. This keeps Adamant platebody rather than an (h1)/(g) skin.
    decorated = "(" in item.name and item.name.rstrip().endswith(")")
    return (item.item_id not in verified_ids, decorated, item.item_id, item.name.casefold())


def observed_account_representatives(
    catalog: EquipmentCatalog,
    account: AccountState,
) -> tuple[ObservedGearRepresentative, ...]:
    """Collapse only exact Wiki-observed equivalents after account legality.

    This intentionally does not use bonus-only Pareto pruning. Observed pages
    still have explicit verification gaps, so an apparently weaker item may
    differ in a special mechanic, attack style, quest gate, or availability.
    """

    eligible = tuple(
        item for item in catalog.observations if _standard_f2p_observation(item) and _requirements_met(item, account)
    )
    groups: dict[str, list[ObservedCatalogItem]] = {}
    for item in eligible:
        groups.setdefault(item.group_signature, []).append(item)

    verified_ids = {item.item_id for item in catalog.verified_items}
    verified_by_coverage: dict[str, list[int]] = {}
    for item in catalog.verified_items:
        signature = EquipmentCatalog._verified_signature(item)
        verified_by_coverage.setdefault(signature, []).append(item.item_id)

    rows: list[ObservedGearRepresentative] = []
    for group in groups.values():
        ordered = sorted(group, key=lambda item: _representative_key(item, verified_ids))
        representative = ordered[0]
        variant_ids = tuple(item.item_id for item in ordered)
        variant_names = tuple(item.name for item in ordered)
        source_urls = tuple(sorted({item.source_url for item in ordered if item.source_url}))
        gaps = tuple(sorted({gap for item in ordered for gap in item.observation.verification_gaps}))
        rows.append(
            ObservedGearRepresentative(
                representative_item_id=representative.item_id,
                representative_name=representative.name,
                slot=representative.slot,
                requirements=dict(representative.requirements),
                bonuses=dict(representative.observation.bonuses),
                attack_speed=representative.observation.attack_speed,
                attack_range=representative.observation.attack_range,
                combat_style=representative.observation.combat_style,
                exact_variant_item_ids=variant_ids,
                exact_variant_names=variant_names,
                source_urls=source_urls,
                verification_gaps=gaps,
                covered_by_verified_item_ids=tuple(
                    sorted(verified_by_coverage.get(representative.coverage_signature, ()))
                ),
            )
        )
    rows.sort(key=lambda row: (row.slot, row.representative_name.casefold(), row.representative_item_id))
    return tuple(rows)


def build_account_gear_export(catalog: EquipmentCatalog, account: AccountState) -> dict[str, Any]:
    observed = observed_account_representatives(catalog, account)
    verified = prune_dominated_items(account, catalog.verified_items)
    verified_names = {item.item_id: item.name for item in catalog.verified_items}
    return {
        "schema_version": 1,
        "purpose": "account-local F2P 1-Defence gear cache and pruning audit",
        "account": {
            "attack": account.attack_level,
            "strength": account.strength_level,
            "ranged": account.ranged_level,
            "magic": account.magic_level,
            "prayer": account.prayer_level,
            "defence": account.defence_level,
            "hitpoints": account.hitpoints_level,
        },
        "source": {
            "query": catalog.query,
            "observation_snapshot_id": catalog.observation_snapshot_id,
            "observation_count": len(catalog.observations),
            "parse_failure_count": len(catalog.failures),
        },
        "method": {
            "observed_filter": (
                "equipable, free_to_play=true, members=false, standard-world source, "
                "and observed skill requirements met by the account"
            ),
            "observed_pruning": "exact observed signature equivalence only",
            "verified_pruning": "account-local strict mechanic-aware Pareto dominance",
            "warning": (
                "Observed representatives are audit/promotion candidates, not solver truth. "
                "Missing quest, availability, attack-style, ammunition, or special-mechanic "
                "evidence prevents strict dominance and solver use until verification."
            ),
        },
        "counts": {
            "account_legal_observed_items_before_exact_collapse": sum(row.exact_variant_count for row in observed),
            "observed_exact_representatives": len(observed),
            "observed_exact_variants_collapsed": sum(row.exact_variant_count - 1 for row in observed),
            "verified_legal_items_before_dominance": len(verified.retained) + len(verified.pruned),
            "verified_dominance_survivors": len(verified.retained),
            "verified_items_pruned": len(verified.pruned),
            "verified_illegal_items": len(verified.rejected_illegal),
        },
        "observed_exact_representatives": [
            {**asdict(row), "exact_variant_count": row.exact_variant_count, "solver_eligible": row.solver_eligible}
            for row in observed
        ],
        "verified_dominance_survivors": [
            {
                "item_id": item.item_id,
                "name": item.name,
                "slot": item.slot,
                "requirements": dict(item.requirements),
                "bonuses": dict(item.bonuses),
                "two_handed": item.two_handed,
                "weapon_type": item.weapon_type,
                "attack_speed": item.attack_speed,
                "attack_range": item.attack_range,
                "attack_styles": item.attack_styles,
                "ammo_ids": item.ammo_ids,
                "spell_ids": item.spell_ids,
                "mechanic_flags": item.mechanic_flags,
                "source_ids": item.source_ids,
            }
            for item in verified.retained
        ],
        "verified_dominance_audit": [
            {
                **asdict(record),
                "dominated_name": verified_names[record.dominated_item_id],
                "dominating_name": verified_names[record.dominating_item_id],
            }
            for record in verified.pruned
        ],
        "verified_illegal_items": [
            {"item_id": item.item_id, "name": item.name, "slot": item.slot} for item in verified.rejected_illegal
        ],
    }


def write_account_gear_json(payload: Mapping[str, Any], output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_observed_representatives_csv(
    rows: Iterable[Mapping[str, Any]],
    output: str | Path,
) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "representative_item_id",
        "representative_name",
        "slot",
        "solver_eligible",
        "covered_by_verified_item_ids",
        "exact_variant_count",
        "exact_variant_item_ids",
        "exact_variant_names",
        *(f"req_{skill}" for skill in REQUIREMENT_COLUMNS),
        *BONUS_COLUMNS,
        "attack_speed",
        "attack_range",
        "combat_style",
        "verification_gaps",
        "source_urls",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            requirements = row["requirements"]
            bonuses = row["bonuses"]
            writer.writerow(
                {
                    "representative_item_id": row["representative_item_id"],
                    "representative_name": row["representative_name"],
                    "slot": row["slot"],
                    "solver_eligible": row["solver_eligible"],
                    "covered_by_verified_item_ids": ";".join(map(str, row["covered_by_verified_item_ids"])),
                    "exact_variant_count": row["exact_variant_count"],
                    "exact_variant_item_ids": ";".join(map(str, row["exact_variant_item_ids"])),
                    "exact_variant_names": ";".join(row["exact_variant_names"]),
                    **{f"req_{skill}": requirements.get(skill, 0) for skill in REQUIREMENT_COLUMNS},
                    **{bonus: bonuses.get(bonus, 0) for bonus in BONUS_COLUMNS},
                    "attack_speed": row["attack_speed"],
                    "attack_range": row["attack_range"],
                    "combat_style": row["combat_style"],
                    "verification_gaps": ";".join(row["verification_gaps"]),
                    "source_urls": ";".join(row["source_urls"]),
                }
            )


def write_verified_survivors_csv(
    rows: Iterable[Mapping[str, Any]],
    output: str | Path,
) -> None:
    """Write the only equipment rows allowed into account-local search."""

    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "item_id",
        "name",
        "slot",
        *(f"req_{skill}" for skill in REQUIREMENT_COLUMNS),
        *BONUS_COLUMNS,
        "two_handed",
        "weapon_type",
        "attack_speed",
        "attack_range",
        "attack_styles",
        "ammo_ids",
        "spell_ids",
        "mechanic_flags",
        "source_ids",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            requirements = row["requirements"]
            bonuses = row["bonuses"]
            writer.writerow(
                {
                    "item_id": row["item_id"],
                    "name": row["name"],
                    "slot": row["slot"],
                    **{f"req_{skill}": requirements.get(skill, 0) for skill in REQUIREMENT_COLUMNS},
                    **{bonus: bonuses.get(bonus, 0) for bonus in BONUS_COLUMNS},
                    "two_handed": row["two_handed"],
                    "weapon_type": row["weapon_type"],
                    "attack_speed": row["attack_speed"],
                    "attack_range": row["attack_range"],
                    "attack_styles": ";".join(row["attack_styles"]),
                    "ammo_ids": ";".join(map(str, row["ammo_ids"])),
                    "spell_ids": ";".join(row["spell_ids"]),
                    "mechanic_flags": ";".join(row["mechanic_flags"]),
                    "source_ids": ";".join(row["source_ids"]),
                }
            )


def write_level_item_profiles_csv(
    profiles: Iterable[LevelItemProfile],
    output: str | Path,
) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    skills = ("attack", "strength", "ranged", "magic", "prayer")
    fieldnames = [
        "profile_id",
        *(column for skill in skills for column in (f"{skill}_min", f"{skill}_max")),
        "defence",
        "retained_item_count",
        "retained_item_ids",
        "retained_item_names",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for profile in profiles:
            writer.writerow(
                {
                    "profile_id": profile.profile_id,
                    **{
                        column: value
                        for skill in skills
                        for column, value in (
                            (f"{skill}_min", profile.level_minimums[skill]),
                            (f"{skill}_max", profile.level_maximums[skill]),
                        )
                    },
                    "defence": 1,
                    "retained_item_count": len(profile.retained_items),
                    "retained_item_ids": ";".join(str(item.item_id) for item in profile.retained_items),
                    "retained_item_names": ";".join(item.name for item in profile.retained_items),
                }
            )


def write_level_item_matrix_csv(
    profiles: Iterable[LevelItemProfile],
    output: str | Path,
) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    skills = ("attack", "strength", "ranged", "magic", "prayer")
    fieldnames = [
        "profile_id",
        *(column for skill in skills for column in (f"{skill}_min", f"{skill}_max")),
        "defence",
        "item_id",
        "item_name",
        "slot",
        *(f"req_{skill}" for skill in REQUIREMENT_COLUMNS),
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for profile in profiles:
            band_columns = {
                column: value
                for skill in skills
                for column, value in (
                    (f"{skill}_min", profile.level_minimums[skill]),
                    (f"{skill}_max", profile.level_maximums[skill]),
                )
            }
            for item in profile.retained_items:
                writer.writerow(
                    {
                        "profile_id": profile.profile_id,
                        **band_columns,
                        "defence": 1,
                        "item_id": item.item_id,
                        "item_name": item.name,
                        "slot": item.slot,
                        **{f"req_{skill}": item.requirements.get(skill, 0) for skill in REQUIREMENT_COLUMNS},
                    }
                )
