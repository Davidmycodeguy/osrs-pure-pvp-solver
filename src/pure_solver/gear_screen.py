"""Conservative screen of a gear-matrix CSV: build a static ``ReductionCandidate`` per row, deduplicate and
Pareto-prune through :mod:`pure_solver.candidate_reduction`, and pick diverse simulator seeds.

The static candidate construction is ported to Rust inside ``pure_math/src/resolved_screen.rs``.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .candidate_reduction import (
    CandidateReductionResult,
    DiverseSeedSelection,
    ReductionCandidate,
    reduce_candidates,
    select_diverse_seeds,
)
from .canonical import canonical_hash
from .gear_catalog_export import BONUS_COLUMNS
from .legality import EquipmentItem

_ITEM_SLOTS = ("head", "neck", "body", "legs", "hands", "weapon", "ammo", "shield")
_ACCOUNT_COLUMNS = (
    "account_attack",
    "account_strength",
    "account_ranged",
    "account_magic",
    "account_prayer",
    "account_defence",
    "account_hitpoints",
)
_BAND_COLUMNS = tuple(
    column
    for skill in ("attack", "strength", "ranged", "magic", "prayer")
    for column in (f"{skill}_min", f"{skill}_max")
)
_REQUIRED_COLUMNS = frozenset(
    {
        "profile_id",
        *_ACCOUNT_COLUMNS,
        *_BAND_COLUMNS,
        *(f"{slot}_id" for slot in _ITEM_SLOTS),
        *(f"{slot}_name" for slot in _ITEM_SLOTS),
        *BONUS_COLUMNS,
        "weapon_type",
        "weapon_attack_speed",
        "weapon_attack_range",
        "weapon_attack_styles",
        "two_handed",
    }
)


def _integer(value: str | None, field: str, *, default: int | None = None) -> int:
    if value in (None, ""):
        if default is not None:
            return default
        raise ValueError(f"Gear matrix row is missing integer field {field!r}")
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"Gear matrix field {field!r} must be an integer") from error


def _boolean(value: str | None, field: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"Gear matrix field {field!r} must be True or False")


@dataclass(frozen=True)
class GearCandidateSource:
    candidate_id: str
    profile_id: int
    account_levels: Mapping[str, int]
    item_ids: Mapping[str, int | None]
    item_names: Mapping[str, str]
    weapon_type: str
    attack_styles: tuple[str, ...]
    attack_speed: int
    attack_range: int
    two_handed: bool

    def to_document(self) -> Mapping[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "profile_id": self.profile_id,
            "account_levels": dict(self.account_levels),
            "items": {
                slot: {"item_id": self.item_ids[slot], "name": self.item_names[slot]}
                for slot in _ITEM_SLOTS
                if self.item_ids[slot] is not None
            },
            "weapon_type": self.weapon_type,
            "attack_styles": self.attack_styles,
            "attack_speed": self.attack_speed,
            "attack_range": self.attack_range,
            "two_handed": self.two_handed,
        }


@dataclass(frozen=True)
class GearMatrixScreenReport:
    input_path: str
    reduction: CandidateReductionResult
    seeds: DiverseSeedSelection
    sources: Mapping[str, GearCandidateSource]
    audit_limit: int

    @property
    def starting_candidates(self) -> int:
        return self.reduction.counts.starting_candidates

    @property
    def simulator_seed_count(self) -> int:
        return len(self.seeds.selected_candidates)

    def to_document(self) -> Mapping[str, object]:
        seed_reasons = {record.candidate_id: record.reasons for record in self.seeds.reasons}
        raw_matchups = self.starting_candidates**2
        initial_active_matchups = self.simulator_seed_count**2
        retained_matchups = self.reduction.counts.remaining_pareto_candidates**2
        return {
            "scope": "verified_gear_matrix_static_screen_v1",
            "input": self.input_path,
            "verification": {
                "status": "verified_for_conservative_static_reduction_only",
                "production_ready": False,
                "full_duel_ranking": False,
                "perfect_play_claim": False,
                "candidate_scope": (
                    "one equipped weapon with full head/neck/body/legs/hands loadout; ammo and shield are derived"
                ),
                "account_profile_scope": (
                    "gear-unlock band representatives, not a complete exact-combat-level account enumeration"
                ),
                "warning": (
                    "This is the safe pre-envelope screen. Short-window adaptive KO envelopes and the "
                    "restricted-policy duel oracle are separate stages; the active set may grow through best responses."
                ),
            },
            "counts": {
                **self.reduction.counts.to_document(),
                "static_frontier_candidates_for_envelope_stage": self.reduction.counts.remaining_pareto_candidates,
                "proposed_initial_active_size": self.simulator_seed_count,
            },
            "work_avoidance": {
                "raw_directional_all_vs_all_matchups": raw_matchups,
                "pareto_directional_all_vs_all_matchups": retained_matchups,
                "projected_initial_active_directional_matchups": initial_active_matchups,
                "projected_directional_matchups_avoided_vs_raw": raw_matchups - initial_active_matchups,
            },
            "proposed_initial_active_candidates": tuple(
                {
                    **self.sources[candidate.candidate_id].to_document(),
                    "selection_reasons": seed_reasons.get(candidate.candidate_id, ()),
                    "normalized_metrics": dict(candidate.normalized_metrics),
                    "capabilities": candidate.capabilities,
                }
                for candidate in self.seeds.selected_candidates
            ),
            "preserved_capability_niches": tuple(
                niche.to_document() for niche in self.reduction.preserved_capability_niches
            ),
            "audit_examples": {
                "exact_duplicates": tuple(
                    record.to_document() for record in self.reduction.exact_duplicate_audits[: self.audit_limit]
                ),
                "dominance": tuple(
                    record.to_document() for record in self.reduction.dominance_audits[: self.audit_limit]
                ),
            },
        }


def _item_mechanics(
    row: Mapping[str, str],
    items_by_id: Mapping[int, EquipmentItem],
) -> tuple[tuple[int, ...], tuple[str, ...], tuple[int, ...], tuple[str, ...]]:
    selected_ids = tuple(
        _integer(row.get(f"{slot}_id"), f"{slot}_id") for slot in ("head", "neck", "body", "legs", "hands", "weapon")
    ) + tuple(
        item_id
        for slot in ("ammo", "shield")
        if (item_id := _integer(row.get(f"{slot}_id"), f"{slot}_id", default=0)) != 0
    )
    try:
        selected = tuple(items_by_id[item_id] for item_id in selected_ids)
    except KeyError as error:
        raise ValueError(f"Gear matrix references item {error.args[0]} absent from the verified ruleset") from error
    flags = tuple(sorted({flag for item in selected for flag in item.mechanic_flags}))
    weapon = items_by_id[_integer(row.get("weapon_id"), "weapon_id")]
    return selected_ids, flags, tuple(sorted(weapon.ammo_ids)), tuple(sorted(weapon.spell_ids))


def _candidate_from_row(
    row: Mapping[str, str],
    *,
    items_by_id: Mapping[int, EquipmentItem],
) -> tuple[ReductionCandidate, GearCandidateSource]:
    profile_id = _integer(row.get("profile_id"), "profile_id")
    account_levels = {column.removeprefix("account_"): _integer(row.get(column), column) for column in _ACCOUNT_COLUMNS}
    level_band = tuple((column, _integer(row.get(column), column)) for column in _BAND_COLUMNS)
    item_ids = {
        slot: (_integer(row.get(f"{slot}_id"), f"{slot}_id") if row.get(f"{slot}_id") not in (None, "") else None)
        for slot in _ITEM_SLOTS
    }
    for slot in ("head", "neck", "body", "legs", "hands", "weapon"):
        if item_ids[slot] is None:
            raise ValueError(f"Static gear screen accepts full loadouts; row is missing {slot}")
    item_names = {slot: str(row.get(f"{slot}_name", "")) for slot in _ITEM_SLOTS}
    styles = tuple(sorted(filter(None, str(row.get("weapon_attack_styles", "")).split(";"))))
    if not styles:
        raise ValueError("Gear matrix weapon has no verified attack styles")
    attack_speed = _integer(row.get("weapon_attack_speed"), "weapon_attack_speed")
    attack_range = _integer(row.get("weapon_attack_range"), "weapon_attack_range")
    two_handed = _boolean(row.get("two_handed"), "two_handed")
    weapon_type = str(row.get("weapon_type") or "unknown")
    selected_ids, mechanic_flags, ammo_ids, spell_ids = _item_mechanics(row, items_by_id)

    metrics = {column: _integer(row.get(column), column) for column in BONUS_COLUMNS}
    metrics.update(
        {
            "attack_speed_quality": -attack_speed,
            "attack_range": attack_range,
        }
    )
    capabilities = {
        *(f"style:{style}" for style in styles),
        *(f"range:at_least:{distance}" for distance in range(1, attack_range + 1)),
        *(f"mechanic:{flag}" for flag in mechanic_flags),
        *(f"spell:{spell_id}" for spell_id in spell_ids),
        f"weapon_type:{weapon_type}",
        "switch:two_handed" if two_handed else "switch:one_handed",
    }
    action_class = {
        "profile_id": profile_id,
        "level_band": level_band,
        "account_levels": account_levels,
        "weapon_type": weapon_type,
        "attack_styles": styles,
        "two_handed": two_handed,
        "mechanic_flags": mechanic_flags,
        "compatible_ammo_ids": ammo_ids,
        "spell_ids": spell_ids,
    }
    candidate_id = canonical_hash(
        {
            "profile_id": profile_id,
            "account_levels": account_levels,
            "item_ids": item_ids,
        }
    )
    equivalence_signature = {
        "action_class": action_class,
        "resolved_metrics": metrics,
        "capabilities": tuple(sorted(capabilities)),
    }
    candidate = ReductionCandidate(
        candidate_id,
        equivalence_signature,
        action_class,
        metrics,
        capabilities,
    )
    source = GearCandidateSource(
        candidate_id=candidate_id,
        profile_id=profile_id,
        account_levels=account_levels,
        item_ids=item_ids,
        item_names=item_names,
        weapon_type=weapon_type,
        attack_styles=styles,
        attack_speed=attack_speed,
        attack_range=attack_range,
        two_handed=two_handed,
    )
    return candidate, source


def screen_gear_matrix_csv(
    path: str | Path,
    items: Iterable[EquipmentItem],
    *,
    seed_size: int = 32,
    audit_limit: int = 20,
) -> GearMatrixScreenReport:
    if seed_size < 1:
        raise ValueError("seed_size must be positive")
    if audit_limit < 0:
        raise ValueError("audit_limit cannot be negative")
    input_path = Path(path)
    items_by_id = {item.item_id: item for item in items}
    candidates: list[ReductionCandidate] = []
    sources: dict[str, GearCandidateSource] = {}
    with input_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = _REQUIRED_COLUMNS - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Gear matrix is missing required columns: {', '.join(sorted(missing))}")
        for row in reader:
            candidate, source = _candidate_from_row(row, items_by_id=items_by_id)
            if candidate.candidate_id in sources:
                raise ValueError(f"Gear matrix contains duplicate structural candidate {candidate.candidate_id}")
            candidates.append(candidate)
            sources[candidate.candidate_id] = source
    if not candidates:
        raise ValueError("Gear matrix contains no candidates")
    reduction = reduce_candidates(candidates)
    seeds = select_diverse_seeds(reduction.retained_candidates, seed_size)
    return GearMatrixScreenReport(str(input_path), reduction, seeds, sources, audit_limit)
