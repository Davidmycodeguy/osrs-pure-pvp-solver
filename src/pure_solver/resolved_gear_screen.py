"""Stage 3: resolve every gear-matrix row into exact integer attack rolls, max hits and cadence KO probabilities
against representative defence rolls, Pareto-prune the resolved rows, and write the survivor manifest and
report.

Ported to Rust as ``pure_math/src/resolved_screen.rs``; this module is the golden reference.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path

from .candidate_reduction import CandidateReductionResult, ReductionCandidate, reduce_candidates
from .canonical import canonical_hash
from .evaluation import DamageDistribution
from .gear_screen import _REQUIRED_COLUMNS, _candidate_from_row
from .legality import EquipmentItem
from .prayers import best_melee_prayer_set, best_ranged_prayer_set
from .ruleset import Ruleset

WINDOWS = (4, 5, 8, 12)
HP_THRESHOLDS = (5, 10, 15, 20, 25, 30)
DEFENCE_TYPES = ("stab", "slash", "crush", "ranged")
_CADENCE_CACHE: dict[tuple[object, ...], tuple[Mapping[str, Fraction], Mapping[str, Fraction]]] = {}
_CADENCE_CACHE_LIMIT = 100_000


def _fraction_document(value: Fraction) -> Mapping[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _quantile(values: Sequence[int], numerator: int, denominator: int) -> int:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Cannot derive representative defence from an empty matrix")
    return ordered[((len(ordered) - 1) * numerator) // denominator]


def _style_parts(style: str) -> tuple[str, str]:
    family, separator, damage_type = style.partition("_")
    if not separator or damage_type not in {*DEFENCE_TYPES}:
        raise ValueError(f"Unsupported matrix attack style {style!r}")
    return family, damage_type


def _style_bonuses(ruleset: Ruleset, family: str) -> Mapping[str, int]:
    configured = ruleset.mechanics.require("combat_style.f2p_bonuses").value
    if not isinstance(configured, Mapping) or not isinstance(configured.get(family), Mapping):
        raise ValueError(f"Missing verified combat-style family {family!r}")
    return {str(key): int(value) for key, value in configured[family].items()}


def _defence_roll(
    ruleset: Ruleset,
    *,
    defence_level: int,
    defence_bonus: int,
    style_bonus: int,
) -> int:
    effective = ruleset.mechanics.evaluate(
        "player.effective_defence",
        {
            "defence_level": defence_level,
            "defence_boost": 0,
            "prayer_multiplier": Fraction(1),
            "style_bonus": style_bonus,
        },
    )
    return int(
        ruleset.mechanics.evaluate(
            "player.defence_roll",
            {
                "effective_defence": effective,
                "defence_bonus": defence_bonus,
            },
        )
    )


@dataclass(frozen=True)
class ResolvedStyle:
    style_id: str
    damage_type: str
    attack_roll: int
    max_hit: int
    potted_max_hit: int
    cooldown_ticks: int
    maximum_range: int
    defence_style_bonus: int


@dataclass(frozen=True)
class ResolvedSource:
    candidate_id: str
    original_row: Mapping[str, str]
    signature: str
    styles: tuple[ResolvedStyle, ...]
    best_expected_damage_per_tick: Mapping[str, Fraction]
    cadence_ko_probabilities: Mapping[str, Fraction]


_BAND_SKILLS = ("attack", "strength", "ranged", "magic", "prayer")
EXACT_ACCOUNT_SCOPE = "exact accounts: every row carries one fully specified 1-Defence profile with reachable Hitpoints"
BAND_ACCOUNT_SCOPE = "gear-unlock band representatives, not exact combat-level-30 accounts"


@dataclass(frozen=True)
class ResolvedGearScreenReport:
    input_path: str
    reduction: CandidateReductionResult
    representative_defence_rolls: Mapping[str, Mapping[str, int]]
    sources: Mapping[str, ResolvedSource]
    audit_limit: int = 20
    account_profile_scope: str = BAND_ACCOUNT_SCOPE

    def to_document(self) -> Mapping[str, object]:
        counts = self.reduction.counts.to_document()
        return {
            "scope": "resolved_single_weapon_gear_envelope_v1",
            "input": self.input_path,
            "verification": {
                "status": "verified_for_resolved_single_weapon_dominance",
                "production_ready": False,
                "perfect_play_claim": False,
                "account_profile_scope": self.account_profile_scope,
                "weapon_scope": "one equipped weapon per row; primary/KO weapon-pair expansion is not included",
                "dominance_proof": (
                    "exact attack rolls, max-hit floors, cooldown/range, per-style defence rolls, HP/Prayer, "
                    "and preserved magic/prayer dimensions"
                ),
                "window_scope": (
                    "cadence-only repeated-weapon PMFs; representative KO metrics are reported "
                    "but are not the sole dominance proof"
                ),
            },
            "counts": {
                **counts,
                "remaining_resolved_options": counts["remaining_pareto_candidates"],
            },
            "windows": WINDOWS,
            "hp_thresholds": HP_THRESHOLDS,
            "representative_defence_rolls": {
                label: dict(values) for label, values in self.representative_defence_rolls.items()
            },
            "manifest_candidate_count": len(self.reduction.retained_candidates),
            "audit_examples": {
                "exact_duplicates": tuple(
                    item.to_document() for item in self.reduction.exact_duplicate_audits[: self.audit_limit]
                ),
                "dominance": tuple(item.to_document() for item in self.reduction.dominance_audits[: self.audit_limit]),
            },
        }


def _resolved_styles(
    ruleset: Ruleset,
    row: Mapping[str, str],
) -> tuple[ResolvedStyle, ...]:
    attack = int(row["account_attack"])
    strength = int(row["account_strength"])
    ranged = int(row["account_ranged"])
    prayer = int(row["account_prayer"])
    base_speed = int(row["weapon_attack_speed"])
    base_range = int(row["weapon_attack_range"])
    melee_prayer = best_melee_prayer_set(ruleset.mechanics, prayer)
    ranged_prayer = best_ranged_prayer_set(ruleset.mechanics, prayer)
    strength_boost = int(ruleset.mechanics.evaluate("strength_potion.boost", {"base_strength": strength}))
    resolved: list[ResolvedStyle] = []
    for style_id in sorted(filter(None, row["weapon_attack_styles"].split(";"))):
        family, damage_type = _style_parts(style_id)
        style = _style_bonuses(ruleset, family)
        if damage_type == "ranged":
            effective_attack = ruleset.mechanics.evaluate(
                "ranged.effective_attack",
                {
                    "ranged_level": ranged,
                    "ranged_boost": 0,
                    "prayer_multiplier": ranged_prayer.multiplier,
                    "style_bonus": style.get("attack", 0),
                    "void_multiplier": Fraction(1),
                },
            )
            effective_strength = ruleset.mechanics.evaluate(
                "ranged.effective_strength",
                {
                    "ranged_level": ranged,
                    "ranged_boost": 0,
                    "prayer_multiplier": ranged_prayer.multiplier,
                    "style_bonus": style.get("strength", 0),
                    "void_multiplier": Fraction(1),
                },
            )
            attack_roll = int(
                ruleset.mechanics.evaluate(
                    "ranged.attack_roll",
                    {
                        "effective_ranged_attack": effective_attack,
                        "ranged_attack_bonus": int(row["attack_ranged"]),
                        "gear_multiplier": Fraction(1),
                    },
                )
            )
            max_hit = int(
                ruleset.mechanics.evaluate(
                    "ranged.max_hit",
                    {
                        "effective_ranged_strength": effective_strength,
                        "ranged_strength_bonus": int(row["ranged_strength"]),
                        "gear_multiplier": Fraction(1),
                    },
                )
            )
            cooldown = (
                int(ruleset.mechanics.evaluate("ranged.rapid_attack_cooldown", {"base_attack_speed": base_speed}))
                if family == "rapid"
                else base_speed
            )
            potted_max_hit = max_hit
        else:
            effective_attack = ruleset.mechanics.evaluate(
                "melee.effective_attack",
                {
                    "attack_level": attack,
                    "attack_boost": 0,
                    "prayer_multiplier": melee_prayer.attack_multiplier,
                    "style_bonus": style.get("attack", 0),
                },
            )
            effective_strength = ruleset.mechanics.evaluate(
                "melee.effective_strength",
                {
                    "strength_level": strength,
                    "strength_boost": 0,
                    "prayer_multiplier": melee_prayer.strength_multiplier,
                    "style_bonus": style.get("strength", 0),
                },
            )
            potted_strength = ruleset.mechanics.evaluate(
                "melee.effective_strength",
                {
                    "strength_level": strength,
                    "strength_boost": strength_boost,
                    "prayer_multiplier": melee_prayer.strength_multiplier,
                    "style_bonus": style.get("strength", 0),
                },
            )
            attack_roll = int(
                ruleset.mechanics.evaluate(
                    "melee.attack_roll",
                    {
                        "effective_attack": effective_attack,
                        "attack_bonus": int(row[f"attack_{damage_type}"]),
                    },
                )
            )
            max_hit = int(
                ruleset.mechanics.evaluate(
                    "melee.max_hit",
                    {
                        "effective_strength": effective_strength,
                        "melee_strength_bonus": int(row["melee_strength"]),
                    },
                )
            )
            potted_max_hit = int(
                ruleset.mechanics.evaluate(
                    "melee.max_hit",
                    {
                        "effective_strength": potted_strength,
                        "melee_strength_bonus": int(row["melee_strength"]),
                    },
                )
            )
            cooldown = base_speed
        resolved.append(
            ResolvedStyle(
                style_id=style_id,
                damage_type=damage_type,
                attack_roll=attack_roll,
                max_hit=max_hit,
                potted_max_hit=potted_max_hit,
                cooldown_ticks=cooldown,
                maximum_range=base_range + style.get("range", 0),
                defence_style_bonus=style.get("defence", 0),
            )
        )
    if not resolved:
        raise ValueError("Gear matrix weapon has no resolved styles")
    return tuple(resolved)


def _representative_rolls(
    ruleset: Ruleset,
    rows: Sequence[Mapping[str, str]],
) -> Mapping[str, Mapping[str, int]]:
    values: dict[str, list[int]] = {damage_type: [] for damage_type in DEFENCE_TYPES}
    for row in rows:
        styles = tuple(filter(None, row["weapon_attack_styles"].split(";")))
        max_defence_style = max(_style_bonuses(ruleset, _style_parts(style)[0]).get("defence", 0) for style in styles)
        for damage_type in DEFENCE_TYPES:
            values[damage_type].append(
                _defence_roll(
                    ruleset,
                    defence_level=int(row["account_defence"]),
                    defence_bonus=int(row[f"defence_{damage_type}"]),
                    style_bonus=max_defence_style,
                )
            )
    return {
        "low": {key: _quantile(item, 1, 10) for key, item in values.items()},
        "medium": {key: _quantile(item, 1, 2) for key, item in values.items()},
        "high": {key: _quantile(item, 9, 10) for key, item in values.items()},
    }


def _cadence_summary(
    ruleset: Ruleset,
    styles: Sequence[ResolvedStyle],
    representative_rolls: Mapping[str, Mapping[str, int]],
) -> tuple[Mapping[str, Fraction], Mapping[str, Fraction]]:
    cache_key = (
        ruleset.mechanics_database_hash,
        tuple((style.damage_type, style.attack_roll, style.max_hit, style.cooldown_ticks) for style in styles),
        tuple((label, tuple(sorted(values.items()))) for label, values in sorted(representative_rolls.items())),
    )
    cached = _CADENCE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    best_damage_per_tick: dict[str, Fraction] = {}
    ko: dict[str, Fraction] = {}
    zero_to_one = bool(ruleset.mechanics.require("damage.player_successful_zero_to_one").value)
    for label, rolls in representative_rolls.items():
        style_distributions: list[tuple[ResolvedStyle, DamageDistribution]] = []
        for style in styles:
            chance = Fraction(
                ruleset.mechanics.evaluate(
                    "melee.accuracy",
                    {
                        "attack_roll": style.attack_roll,
                        "defence_roll": rolls[style.damage_type],
                    },
                )
            )
            style_distributions.append(
                (
                    style,
                    DamageDistribution.from_success_chance(chance, style.max_hit, zero_to_one),
                )
            )
        best_damage_per_tick[label] = max(
            distribution.expected_damage / style.cooldown_ticks for style, distribution in style_distributions
        )
        for window in WINDOWS:
            best_by_hp = {hp: Fraction(0) for hp in HP_THRESHOLDS}
            for style, distribution in style_distributions:
                attacks = 1 + (window - 1) // style.cooldown_ticks
                total = DamageDistribution({0: Fraction(1)})
                for _ in range(attacks):
                    probability: dict[int, Fraction] = {}
                    for left, left_chance in total.probability.items():
                        for right, right_chance in distribution.probability.items():
                            probability[left + right] = (
                                probability.get(left + right, Fraction(0)) + left_chance * right_chance
                            )
                    total = DamageDistribution(probability)
                for hp in HP_THRESHOLDS:
                    best_by_hp[hp] = max(
                        best_by_hp[hp],
                        sum(chance for damage, chance in total.probability.items() if damage >= hp),
                    )
            for hp, value in best_by_hp.items():
                ko[f"{label}:{window}:{hp}"] = value
    result = (best_damage_per_tick, ko)
    if len(_CADENCE_CACHE) >= _CADENCE_CACHE_LIMIT:
        _CADENCE_CACHE.clear()
    _CADENCE_CACHE[cache_key] = result
    return result


def _resolved_candidate(
    ruleset: Ruleset,
    row: Mapping[str, str],
    *,
    items_by_id: Mapping[int, EquipmentItem],
) -> tuple[ReductionCandidate, ResolvedSource]:
    static_candidate, source = _candidate_from_row(row, items_by_id=items_by_id)
    styles = _resolved_styles(ruleset, row)
    metrics: dict[str, int | Fraction] = {}
    for style in styles:
        prefix = f"style:{style.style_id}"
        metrics[f"{prefix}:attack_roll"] = style.attack_roll
        metrics[f"{prefix}:max_hit"] = style.max_hit
        metrics[f"{prefix}:potted_max_hit"] = style.potted_max_hit
        metrics[f"{prefix}:cooldown_quality"] = -style.cooldown_ticks
        metrics[f"{prefix}:maximum_range"] = style.maximum_range
        for damage_type in DEFENCE_TYPES:
            metrics[f"{prefix}:defence_roll:{damage_type}"] = _defence_roll(
                ruleset,
                defence_level=int(row["account_defence"]),
                defence_bonus=int(row[f"defence_{damage_type}"]),
                style_bonus=style.defence_style_bonus,
            )
    metrics.update(
        {
            "magic_attack_bonus": int(row["attack_magic"]),
            "magic_defence_bonus": int(row["defence_magic"]),
            "magic_damage_percent": int(row["magic_damage"]),
            "prayer_bonus": int(row["prayer"]),
            "hitpoints": int(row["account_hitpoints"]),
            "prayer_level": int(row["account_prayer"]),
        }
    )
    signature = canonical_hash(
        {
            "comparison_class": static_candidate.comparison_class,
            "resolved_metrics": tuple(sorted(metrics.items())),
            "capabilities": static_candidate.capabilities,
        }
    )
    candidate = ReductionCandidate(
        static_candidate.candidate_id,
        equivalence_signature=signature,
        comparison_class=static_candidate.comparison_class,
        normalized_metrics=metrics,
        capabilities=static_candidate.capabilities,
    )
    return candidate, ResolvedSource(
        candidate_id=candidate.candidate_id,
        original_row=dict(row),
        signature=signature,
        styles=styles,
        best_expected_damage_per_tick={},
        cadence_ko_probabilities={},
    )


def screen_resolved_gear_matrix_csv(
    path: str | Path,
    ruleset: Ruleset,
    *,
    audit_limit: int = 20,
) -> ResolvedGearScreenReport:
    input_path = Path(path)
    items_by_id = {item.item_id: item for item in (EquipmentItem.from_document(document) for document in ruleset.items)}
    with input_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = _REQUIRED_COLUMNS - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Gear matrix is missing required columns: {', '.join(sorted(missing))}")
        rows = tuple(dict(row) for row in reader)
    if not rows:
        raise ValueError("Gear matrix contains no candidates")
    representative = _representative_rolls(ruleset, rows)
    candidates: list[ReductionCandidate] = []
    sources: dict[str, ResolvedSource] = {}
    for row in rows:
        candidate, source = _resolved_candidate(
            ruleset,
            row,
            items_by_id=items_by_id,
        )
        if candidate.candidate_id in sources:
            raise ValueError(f"Gear matrix contains duplicate structural candidate {candidate.candidate_id}")
        candidates.append(candidate)
        sources[candidate.candidate_id] = source
    reduction = reduce_candidates(candidates)
    for retained in reduction.retained_candidates:
        source = sources[retained.candidate_id]
        best_damage_per_tick, ko = _cadence_summary(ruleset, source.styles, representative)
        sources[retained.candidate_id] = replace(
            source,
            best_expected_damage_per_tick=best_damage_per_tick,
            cadence_ko_probabilities=ko,
        )
    return ResolvedGearScreenReport(
        str(input_path),
        reduction,
        representative,
        sources,
        audit_limit,
        account_profile_scope=_account_profile_scope(rows),
    )


def _account_profile_scope(rows: Sequence[Mapping[str, str]]) -> str:
    exact = all(
        row[f"{skill}_min"] == row[f"{skill}_max"] == row[f"account_{skill}"] for row in rows for skill in _BAND_SKILLS
    )
    return EXACT_ACCOUNT_SCOPE if exact else BAND_ACCOUNT_SCOPE


def write_resolved_survivor_manifest(
    report: ResolvedGearScreenReport,
    output: str | Path,
) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    survivor_ids = {candidate.candidate_id for candidate in report.reduction.retained_candidates}
    source_fieldnames = tuple(next(iter(report.sources.values())).original_row)
    fieldnames = (
        "candidate_id",
        "resolved_signature",
        "resolved_styles_json",
        "best_expected_damage_per_tick_json",
        "cadence_ko_probabilities_json",
        "cadence_ko_scope",
        *source_fieldnames,
    )
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for candidate_id in sorted(survivor_ids):
            source = report.sources[candidate_id]
            writer.writerow(
                {
                    "candidate_id": candidate_id,
                    "resolved_signature": source.signature,
                    "resolved_styles_json": json.dumps(
                        [
                            {
                                "style_id": style.style_id,
                                "damage_type": style.damage_type,
                                "attack_roll": style.attack_roll,
                                "max_hit": style.max_hit,
                                "potted_max_hit": style.potted_max_hit,
                                "cooldown_ticks": style.cooldown_ticks,
                                "maximum_range": style.maximum_range,
                            }
                            for style in source.styles
                        ],
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    "best_expected_damage_per_tick_json": json.dumps(
                        {
                            key: _fraction_document(value)
                            for key, value in sorted(source.best_expected_damage_per_tick.items())
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    "cadence_ko_probabilities_json": json.dumps(
                        {
                            key: _fraction_document(value)
                            for key, value in sorted(source.cadence_ko_probabilities.items())
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    "cadence_ko_scope": "repeated_weapon_cooldown_only_no_projectile_delay_or_switching",
                    **source.original_row,
                }
            )
    temporary.replace(path)


def write_resolved_gear_report(
    report: ResolvedGearScreenReport,
    output: str | Path,
) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report.to_document(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
