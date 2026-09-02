"""Stage 4: rank every resolved survivor for simulator priority (never a prune) using a diverse opponent panel,
exact food-race margins, category percentiles and extreme flags, and write the ranked CSV and report.

Ported to Rust as ``pure_math/src/ranking/``; this module is the golden reference.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

from .ruleset import Ruleset

# This module deliberately ranks rather than prunes.  The input has already
# passed the conservative exact-equivalence/Pareto screen.  The race model and
# equal-weight category score below are useful heuristics for deciding which
# candidates deserve expensive simulation first, but they are not proofs that
# a lower-ranked candidate is strategically irrelevant.
DEFENCE_STATES = ("low", "medium", "high")
WINDOWS = (4, 5, 8, 12)
HP_THRESHOLDS = (5, 10, 15, 20, 25, 30)
DAMAGE_TYPES = ("stab", "slash", "crush", "ranged")
DEFAULT_EAT_PENALTIES = (3, 0)

# The ranked CSV already contains exact aggregate DPT/KO fields.  Repeating the
# 70+ cadence probabilities for every survivor row would add hundreds of megabytes
# without adding a stat or gear column, so only those two aggregate source
# blobs are omitted from the enriched presentation artifact.
_OMITTED_SOURCE_BLOBS = {
    "best_expected_damage_per_tick_json",
    "cadence_ko_probabilities_json",
}

_REQUIRED_COLUMNS = {
    "candidate_id",
    "resolved_signature",
    "resolved_styles_json",
    "best_expected_damage_per_tick_json",
    "cadence_ko_probabilities_json",
    "cadence_ko_scope",
    "profile_id",
    "account_attack",
    "account_strength",
    "account_ranged",
    "account_magic",
    "account_prayer",
    "account_defence",
    "account_hitpoints",
    "attack_magic",
    "defence_stab",
    "defence_slash",
    "defence_crush",
    "defence_magic",
    "defence_ranged",
    "prayer",
    "weapon_type",
    "weapon_name",
    "weapon_slot",
    "two_handed",
    "head_name",
    "neck_name",
    "body_name",
    "legs_name",
    "hands_name",
    "ammo_name",
    "shield_name",
}


def _fraction_document(value: Fraction) -> Mapping[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def _mean(values: Sequence[Fraction]) -> Fraction:
    if not values:
        raise ValueError("Cannot average an empty sequence")
    return sum(values, Fraction(0)) / len(values)


def _quantile(values: Sequence[Fraction], numerator: int, denominator: int) -> Fraction:
    if not values:
        raise ValueError("Cannot take a quantile of an empty sequence")
    ordered = sorted(values)
    return ordered[((len(ordered) - 1) * numerator) // denominator]


def _integer(row: Mapping[str, str], column: str, candidate_id: str) -> int:
    try:
        return int(row[column])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Candidate {candidate_id!r} has invalid integer column {column!r}") from error


def _boolean(row: Mapping[str, str], column: str, candidate_id: str) -> bool:
    value = str(row.get(column, "")).strip().lower()
    if value in {"1", "true", "yes"}:
        return True
    if value in {"0", "false", "no"}:
        return False
    raise ValueError(f"Candidate {candidate_id!r} has invalid boolean column {column!r}")


def _json_value(row: Mapping[str, str], column: str, candidate_id: str) -> object:
    try:
        return json.loads(row[column])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"Candidate {candidate_id!r} has invalid JSON column {column!r}") from error


def _json_integer(value: object, *, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{context} must be an integer")
    return value


def _parse_fraction(value: object, *, context: str, probability: bool = False) -> Fraction:
    if not isinstance(value, Mapping) or set(value) != {"numerator", "denominator"}:
        raise ValueError(f"{context} must contain exactly numerator and denominator")
    numerator = value["numerator"]
    denominator = value["denominator"]
    if (
        not isinstance(numerator, int)
        or isinstance(numerator, bool)
        or not isinstance(denominator, int)
        or isinstance(denominator, bool)
    ):
        raise ValueError(f"{context} has non-integer numerator or denominator")
    if denominator <= 0:
        raise ValueError(f"{context} denominator must be positive")
    result = Fraction(numerator, denominator)
    if probability and not 0 <= result <= 1:
        raise ValueError(f"{context} must be a probability")
    return result


@dataclass(frozen=True, slots=True)
class RankingStyle:
    style_id: str
    damage_type: str
    attack_roll: int
    max_hit: int
    potted_max_hit: int
    cooldown_ticks: int
    maximum_range: int


@dataclass(frozen=True, slots=True)
class RankingCandidate:
    candidate_id: str
    resolved_signature: str
    profile_id: int
    levels: tuple[int, int, int, int, int, int, int]
    styles: tuple[RankingStyle, ...]
    sustained_dpt: tuple[Fraction, Fraction, Fraction]
    ko_by_window: tuple[Fraction, Fraction, Fraction, Fraction]
    defence_rolls: tuple[int, int, int, int]
    magic_attack_bonus: int
    magic_defence_bonus: int
    prayer_bonus: int
    weapon_type: str
    weapon_name: str
    weapon_slot: str
    two_handed: bool
    equipment_names: tuple[str, str, str, str, str, str, str, str]
    cadence_ko_scope: str

    @property
    def hitpoints(self) -> int:
        return self.levels[6]

    @property
    def prayer_level(self) -> int:
        return self.levels[4]

    @property
    def max_hit(self) -> int:
        return max(style.max_hit for style in self.styles)

    @property
    def maximum_attack_roll(self) -> int:
        return max(style.attack_roll for style in self.styles)

    @property
    def potted_max_hit(self) -> int:
        return max(style.potted_max_hit for style in self.styles)

    @property
    def maximum_range(self) -> int:
        return max(style.maximum_range for style in self.styles)

    @property
    def damage_types(self) -> tuple[str, ...]:
        return tuple(sorted({style.damage_type for style in self.styles}))

    @property
    def sustain_average(self) -> Fraction:
        return _mean(self.sustained_dpt)

    @property
    def sustain_worst(self) -> Fraction:
        return min(self.sustained_dpt)

    @property
    def physical_defence_average(self) -> Fraction:
        return _mean(tuple(Fraction(value) for value in self.defence_rolls))


@dataclass(frozen=True, slots=True)
class RaceScenario:
    eat_penalty: int
    opponent_count: int
    worst_margin_fish: Fraction
    tenth_percentile_margin_fish: Fraction
    mean_margin_fish: Fraction
    win_fraction: Fraction


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    candidate: RankingCandidate
    rank: int
    tier: str
    overall_score: Fraction
    category_scores: tuple[tuple[str, Fraction], ...]
    race_scenarios: tuple[RaceScenario, ...]
    niche_flags: tuple[str, ...]
    rank_reasons: tuple[str, ...]
    simulator_seed_reasons: tuple[str, ...]

    @property
    def category_map(self) -> Mapping[str, Fraction]:
        return dict(self.category_scores)


@dataclass(frozen=True, slots=True)
class SurvivorRankingReport:
    input_path: str
    rankings: tuple[RankedCandidate, ...]
    panel_candidate_ids: tuple[str, ...]
    panel_reasons: Mapping[str, tuple[str, ...]]
    ranking_self_matchup_reserve_candidate_id: str | None
    food_slots: int
    heal_per_eat: int
    eat_penalties: tuple[int, ...]
    preview_size: int

    @property
    def tier_counts(self) -> Mapping[str, int]:
        counts = {tier: 0 for tier in ("S", "A", "B", "N", "C")}
        for ranked in self.rankings:
            counts[ranked.tier] += 1
        return counts

    def to_document(self) -> Mapping[str, object]:
        candidate_count = len(self.rankings)
        panel_count = len(self.panel_candidate_ids)
        return {
            "scope": "resolved_single_weapon_candidate_priority_ranking_v1",
            "input": self.input_path,
            "verification": {
                "status": "heuristic_priority_order_only",
                "production_ready": False,
                "perfect_play_claim": False,
                "deletes_candidates": False,
                "candidate_scope": (
                    "resolved single-equipped-weapon gear-unlock representatives; not complete combat-level-30 accounts"
                ),
                "combat_scope": (
                    "stationary cadence damage plus a notional attrition race; no movement, "
                    "projectile arrival alignment, weapon switching, spell damage, prayer "
                    "activation, potion timing, or opponent policy"
                ),
                "inventory_scope": (
                    "equal notional food slots for every row; carried switches, runes, "
                    "potions, and food composition are deferred to kit/simulator search"
                ),
                "authority": "the later mechanics-faithful simulator/RL solver remains final",
            },
            "counts": {
                "input_candidates": candidate_count,
                "ranked_candidates": candidate_count,
                "candidates_removed_by_ranking": 0,
                "recommended_initial_simulator_candidates": panel_count,
                "cheap_envelope_panel_pairings": (
                    candidate_count * panel_count
                    if candidate_count > panel_count
                    else candidate_count * max(1, candidate_count - 1)
                ),
                "full_unordered_nonself_matchups": candidate_count * (candidate_count - 1) // 2,
                "full_directed_nonself_matchups": candidate_count * (candidate_count - 1),
                "full_directed_matrix_cells": candidate_count * candidate_count,
                "initial_panel_unordered_nonself_matchups": panel_count * (panel_count - 1) // 2,
                "initial_panel_directed_nonself_matchups": panel_count * (panel_count - 1),
                "initial_panel_directed_matrix_cells": panel_count * panel_count,
                "expensive_matchup_solves_run_by_this_command": 0,
                "tier_counts": dict(self.tier_counts),
            },
            "formula": {
                "successful_hit_expected_damage": (
                    "p_hit * (max_hit/2 + 1/(max_hit+1)) when PvP successful 0 becomes 1"
                ),
                "uptime": "heal_per_eat / (heal_per_eat + eat_penalty * incoming_dpt)",
                "race_margin": (
                    "signed extra survival ticks multiplied by the loser's effective dpt, "
                    "reported in heal_per_eat units"
                ),
                "panel_self_matchups": (
                    "excluded; panel rows face one deterministic ranking-only reserve "
                    "so every real candidate has the same number of distinct opponents"
                ),
                "category_scores": {
                    "sustain": "mean population midrank percentile of low/medium/high exact DPT",
                    "race": "mean percentile of robust worst, penalty-3 p10/mean, and penalty-0 mean margins",
                    "burst": "mean percentile of 4/5/8/12-tick cadence KO, max hit, and potted max hit",
                    "defence": "mean percentile of stab/slash/crush/ranged defence rolls and magic defence bonus",
                    "utility": "mean percentile of range, style breadth, Prayer level/bonus, and magic attack bonus",
                },
                "overall_score": "equal-weight mean of sustain, race, burst, defence, and utility category percentiles",
                "tie_break": "race, burst, sustain, defence, utility, then candidate_id",
                "tiers": "S top 1%; A next to 5%; B next to 20%; N lower-ranked panel/extreme niche; C remainder",
            },
            "configuration": {
                "food_slots": self.food_slots,
                "heal_per_eat": self.heal_per_eat,
                "eat_penalties": self.eat_penalties,
                "panel_size": panel_count,
                "ranking_self_matchup_reserve_candidate_id": (self.ranking_self_matchup_reserve_candidate_id),
            },
            "simulator_seed_panel": tuple(
                {
                    "candidate_id": candidate_id,
                    "selection_reasons": self.panel_reasons[candidate_id],
                }
                for candidate_id in self.panel_candidate_ids
            ),
            "top_preview": tuple(_ranked_document(ranked) for ranked in self.rankings[: self.preview_size]),
        }


def _style_family(style_id: str) -> str:
    family, separator, _ = style_id.partition("_")
    if not separator:
        raise ValueError(f"Unsupported resolved style ID {style_id!r}")
    return family


def _style_defence_bonus(ruleset: Ruleset, style_id: str) -> int:
    configured = ruleset.mechanics.require("combat_style.f2p_bonuses").value
    family = _style_family(style_id)
    if not isinstance(configured, Mapping) or not isinstance(configured.get(family), Mapping):
        raise ValueError(f"Missing verified combat-style family {family!r}")
    return int(configured[family].get("defence", 0))


def _defence_rolls(
    ruleset: Ruleset,
    row: Mapping[str, str],
    styles: Sequence[RankingStyle],
    candidate_id: str,
) -> tuple[int, int, int, int]:
    # A row can expose multiple combat styles.  We use its best available
    # defensive style here, matching the representative-defence screen.  This
    # is optimistic and is therefore reported as a ranking heuristic, not a
    # simultaneous attack/defence policy solve.
    style_bonus = max(_style_defence_bonus(ruleset, style.style_id) for style in styles)
    effective = ruleset.mechanics.evaluate(
        "player.effective_defence",
        {
            "defence_level": _integer(row, "account_defence", candidate_id),
            "defence_boost": 0,
            "prayer_multiplier": Fraction(1),
            "style_bonus": style_bonus,
        },
    )
    return tuple(
        int(
            ruleset.mechanics.evaluate(
                "player.defence_roll",
                {
                    "effective_defence": effective,
                    "defence_bonus": _integer(row, f"defence_{damage_type}", candidate_id),
                },
            )
        )
        for damage_type in DAMAGE_TYPES
    )


def _parse_styles(value: object, candidate_id: str) -> tuple[RankingStyle, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Candidate {candidate_id!r} resolved styles must be a non-empty list")
    styles: list[RankingStyle] = []
    required = {
        "style_id",
        "damage_type",
        "attack_roll",
        "max_hit",
        "potted_max_hit",
        "cooldown_ticks",
        "maximum_range",
    }
    for index, item in enumerate(value):
        if not isinstance(item, Mapping) or not required <= set(item):
            raise ValueError(f"Candidate {candidate_id!r} resolved style {index} is missing required fields")
        context = f"Candidate {candidate_id!r} resolved style {index}"
        if (
            not isinstance(item["style_id"], str)
            or not item["style_id"]
            or not isinstance(item["damage_type"], str)
            or not item["damage_type"]
        ):
            raise ValueError(f"{context} has invalid style_id or damage_type")
        style = RankingStyle(
            style_id=item["style_id"],
            damage_type=item["damage_type"],
            attack_roll=_json_integer(item["attack_roll"], context=f"{context} attack_roll"),
            max_hit=_json_integer(item["max_hit"], context=f"{context} max_hit"),
            potted_max_hit=_json_integer(item["potted_max_hit"], context=f"{context} potted_max_hit"),
            cooldown_ticks=_json_integer(item["cooldown_ticks"], context=f"{context} cooldown_ticks"),
            maximum_range=_json_integer(item["maximum_range"], context=f"{context} maximum_range"),
        )
        if style.damage_type not in DAMAGE_TYPES:
            raise ValueError(f"Candidate {candidate_id!r} has unsupported damage type {style.damage_type!r}")
        if (
            style.attack_roll < 0
            or style.max_hit < 0
            or style.potted_max_hit < 0
            or style.cooldown_ticks <= 0
            or style.maximum_range <= 0
        ):
            raise ValueError(f"Candidate {candidate_id!r} has invalid resolved style values")
        styles.append(style)
    style_ids = [style.style_id for style in styles]
    if len(style_ids) != len(set(style_ids)):
        raise ValueError(f"Candidate {candidate_id!r} has duplicate resolved style IDs")
    return tuple(sorted(styles, key=lambda style: style.style_id))


def _parse_candidate(
    row: Mapping[str, str],
    ruleset: Ruleset,
) -> RankingCandidate:
    candidate_id = str(row.get("candidate_id", "")).strip()
    if not candidate_id:
        raise ValueError("Resolved survivor row has no candidate_id")
    styles = _parse_styles(_json_value(row, "resolved_styles_json", candidate_id), candidate_id)

    dpt_document = _json_value(row, "best_expected_damage_per_tick_json", candidate_id)
    if not isinstance(dpt_document, Mapping):
        raise ValueError(f"Candidate {candidate_id!r} DPT document must be an object")
    sustained = tuple(
        _parse_fraction(dpt_document.get(state), context=f"{candidate_id} DPT {state}") for state in DEFENCE_STATES
    )
    if any(value < 0 for value in sustained):
        raise ValueError(f"Candidate {candidate_id!r} has negative expected damage")

    ko_document = _json_value(row, "cadence_ko_probabilities_json", candidate_id)
    if not isinstance(ko_document, Mapping):
        raise ValueError(f"Candidate {candidate_id!r} KO document must be an object")
    ko_by_window: list[Fraction] = []
    for window in WINDOWS:
        values = tuple(
            _parse_fraction(
                ko_document.get(f"{state}:{window}:{hp}"),
                context=f"{candidate_id} KO {state}:{window}:{hp}",
                probability=True,
            )
            for state in DEFENCE_STATES
            for hp in HP_THRESHOLDS
        )
        ko_by_window.append(_mean(values))

    levels = tuple(
        _integer(row, column, candidate_id)
        for column in (
            "account_attack",
            "account_strength",
            "account_ranged",
            "account_magic",
            "account_prayer",
            "account_defence",
            "account_hitpoints",
        )
    )
    if any(level < 1 for level in levels):
        raise ValueError(f"Candidate {candidate_id!r} has a level below 1")

    equipment_names = tuple(
        str(row.get(column, ""))
        for column in (
            "head_name",
            "neck_name",
            "body_name",
            "legs_name",
            "hands_name",
            "weapon_name",
            "ammo_name",
            "shield_name",
        )
    )
    cadence_scope = str(row["cadence_ko_scope"])
    expected_cadence_scope = "repeated_weapon_cooldown_only_no_projectile_delay_or_switching"
    if cadence_scope != expected_cadence_scope:
        raise ValueError(f"Candidate {candidate_id!r} has unsupported cadence KO scope {cadence_scope!r}")
    return RankingCandidate(
        candidate_id=candidate_id,
        resolved_signature=str(row["resolved_signature"]),
        profile_id=_integer(row, "profile_id", candidate_id),
        levels=levels,
        styles=styles,
        sustained_dpt=sustained,
        ko_by_window=tuple(ko_by_window),  # type: ignore[arg-type]
        defence_rolls=_defence_rolls(ruleset, row, styles, candidate_id),
        magic_attack_bonus=_integer(row, "attack_magic", candidate_id),
        magic_defence_bonus=_integer(row, "defence_magic", candidate_id),
        prayer_bonus=_integer(row, "prayer", candidate_id),
        weapon_type=str(row["weapon_type"]),
        weapon_name=str(row["weapon_name"]),
        weapon_slot=str(row["weapon_slot"]),
        two_handed=_boolean(row, "two_handed", candidate_id),
        equipment_names=equipment_names,  # type: ignore[arg-type]
        cadence_ko_scope=cadence_scope,
    )


def load_ranking_candidates(path: str | Path, ruleset: Ruleset) -> tuple[RankingCandidate, ...]:
    input_path = Path(path)
    candidates: list[RankingCandidate] = []
    seen: set[str] = set()
    with input_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = _REQUIRED_COLUMNS - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Resolved survivor manifest is missing required columns: {', '.join(sorted(missing))}")
        for row in reader:
            candidate = _parse_candidate(row, ruleset)
            if candidate.candidate_id in seen:
                raise ValueError(f"Resolved survivor manifest contains duplicate candidate {candidate.candidate_id}")
            seen.add(candidate.candidate_id)
            candidates.append(candidate)
    if not candidates:
        raise ValueError("Resolved survivor manifest contains no candidates")
    return tuple(sorted(candidates, key=lambda candidate: candidate.candidate_id))


def _panel_features(candidate: RankingCandidate) -> tuple[Fraction, ...]:
    return (
        *candidate.sustained_dpt,
        *candidate.ko_by_window,
        Fraction(candidate.max_hit),
        Fraction(candidate.potted_max_hit),
        Fraction(candidate.maximum_range),
        candidate.physical_defence_average,
        Fraction(candidate.magic_attack_bonus),
        Fraction(candidate.magic_defence_bonus),
        Fraction(candidate.prayer_bonus),
    )


def _best_candidate(
    candidates: Sequence[RankingCandidate],
    score,
) -> RankingCandidate:
    return min(candidates, key=lambda candidate: (-score(candidate), candidate.candidate_id))


def _select_panel(
    candidates: Sequence[RankingCandidate],
    requested_size: int,
) -> tuple[tuple[RankingCandidate, ...], Mapping[str, tuple[str, ...]]]:
    if requested_size < 1:
        raise ValueError("panel_size must be positive")
    requested_size = min(requested_size, len(candidates))
    selected: list[RankingCandidate] = []
    reasons: dict[str, list[str]] = {}

    def add(candidate: RankingCandidate, reason: str) -> None:
        if candidate.candidate_id in reasons:
            reasons[candidate.candidate_id].append(reason)
        elif len(selected) < requested_size:
            selected.append(candidate)
            reasons[candidate.candidate_id] = [reason]

    forced = (
        ("sustain_average_extreme", lambda candidate: candidate.sustain_average),
        ("sustain_worst_extreme", lambda candidate: candidate.sustain_worst),
        ("four_tick_ko_extreme", lambda candidate: candidate.ko_by_window[0]),
        ("twelve_tick_ko_extreme", lambda candidate: candidate.ko_by_window[3]),
        ("potted_max_hit_extreme", lambda candidate: Fraction(candidate.potted_max_hit)),
        ("physical_defence_extreme", lambda candidate: candidate.physical_defence_average),
        ("magic_defence_extreme", lambda candidate: Fraction(candidate.magic_defence_bonus)),
        ("magic_attack_gear_extreme", lambda candidate: Fraction(candidate.magic_attack_bonus)),
        ("range_extreme", lambda candidate: Fraction(candidate.maximum_range)),
        ("prayer_bonus_extreme", lambda candidate: Fraction(candidate.prayer_bonus)),
    )
    for reason, score in forced:
        add(_best_candidate(candidates, score), reason)

    # Force at least one strong representative of every damage type before
    # using geometry.  This prevents a melee-heavy population from crowding
    # ranged or crush/stab counter candidates out of the simulator seed set.
    for damage_type in DAMAGE_TYPES:
        eligible = [candidate for candidate in candidates if damage_type in candidate.damage_types]
        if eligible:
            add(
                _best_candidate(eligible, lambda candidate: candidate.sustain_average),
                f"damage_type_representative:{damage_type}",
            )

    # Weapon-type representatives are cheap insurance for action/timing
    # differences that the envelope does not fully price.
    for weapon_type in sorted({candidate.weapon_type for candidate in candidates}):
        eligible = [candidate for candidate in candidates if candidate.weapon_type == weapon_type]
        add(
            _best_candidate(eligible, lambda candidate: candidate.sustain_average),
            f"weapon_type_representative:{weapon_type}",
        )

    feature_rows = [_panel_features(candidate) for candidate in candidates]
    dimensions = len(feature_rows[0])

    # Convert every feature to an exact integer midrank on the same
    # 0..2*(N-1) scale.  This avoids both floating-point panel instability and
    # millions of expensive Fraction squares in farthest-point selection.
    rank_vectors = [[0] * dimensions for _ in candidates]
    for dimension in range(dimensions):
        values = [row[dimension] for row in feature_rows]
        ordered = sorted(values)
        rank_by_value = {value: bisect_left(ordered, value) + bisect_right(ordered, value) - 1 for value in set(values)}
        for index, value in enumerate(values):
            rank_vectors[index][dimension] = rank_by_value[value]
    index_by_id = {candidate.candidate_id: index for index, candidate in enumerate(candidates)}

    def distance(left: int, right: int) -> int:
        return sum(
            ((rank_vectors[left][index] - rank_vectors[right][index]) ** 2 for index in range(dimensions)),
            0,
        )

    selected_indices = [index_by_id[candidate.candidate_id] for candidate in selected]
    if selected_indices:
        minimum_distance = [
            min(distance(index, selected_index) for selected_index in selected_indices)
            for index in range(len(candidates))
        ]
    else:
        minimum_distance = [0 for _ in candidates]
    selected_ids = set(reasons)
    while len(selected) < requested_size:
        remaining_indices = [
            index for index, candidate in enumerate(candidates) if candidate.candidate_id not in selected_ids
        ]
        next_index = min(
            remaining_indices,
            key=lambda index: (
                -minimum_distance[index],
                -candidates[index].sustain_average,
                candidates[index].candidate_id,
            ),
        )
        candidate = candidates[next_index]
        add(candidate, "envelope_farthest_point")
        selected_ids.add(candidate.candidate_id)
        for index in remaining_indices:
            minimum_distance[index] = min(minimum_distance[index], distance(index, next_index))

    return (
        tuple(selected),
        {candidate.candidate_id: tuple(reasons[candidate.candidate_id]) for candidate in selected},
    )


@lru_cache(maxsize=500_000)
def _style_dpt(
    attack_roll: int,
    defence_roll: int,
    max_hit: int,
    cooldown_ticks: int,
    successful_zero_to_one: bool,
) -> Fraction:
    if attack_roll > defence_roll:
        accuracy = 1 - Fraction(defence_roll + 2, 2 * (attack_roll + 1))
    else:
        accuracy = Fraction(attack_roll, 2 * (defence_roll + 1))
    if max_hit == 0:
        expected_success = Fraction(0)
    else:
        expected_success = Fraction(max_hit, 2)
        if successful_zero_to_one:
            expected_success += Fraction(1, max_hit + 1)
    return accuracy * expected_success / cooldown_ticks


def _best_dpt(
    attacker: RankingCandidate,
    defender: RankingCandidate,
    successful_zero_to_one: bool,
) -> Fraction:
    defence_by_type = dict(zip(DAMAGE_TYPES, defender.defence_rolls, strict=True))
    return max(
        _style_dpt(
            style.attack_roll,
            defence_by_type[style.damage_type],
            style.max_hit,
            style.cooldown_ticks,
            successful_zero_to_one,
        )
        for style in attacker.styles
    )


def _race_margin(
    candidate: RankingCandidate,
    opponent: RankingCandidate,
    *,
    eat_penalty: int,
    food_slots: int,
    heal_per_eat: int,
    successful_zero_to_one: bool,
) -> Fraction:
    outgoing = _best_dpt(candidate, opponent, successful_zero_to_one)
    incoming = _best_dpt(opponent, candidate, successful_zero_to_one)
    if outgoing == incoming == 0:
        return Fraction(0)
    if outgoing == 0:
        return -Fraction(candidate.hitpoints + food_slots * heal_per_eat, heal_per_eat)
    if incoming == 0:
        return Fraction(opponent.hitpoints + food_slots * heal_per_eat, heal_per_eat)

    # This is the closed-form attrition approximation.  Every candidate is
    # assigned the same notional inventory, so it ranks combat envelopes
    # without inventing switch/rune/potion costs that do not exist in this CSV.
    candidate_uptime = Fraction(heal_per_eat, heal_per_eat + eat_penalty * incoming)
    opponent_uptime = Fraction(heal_per_eat, heal_per_eat + eat_penalty * outgoing)
    candidate_effective = outgoing * candidate_uptime
    opponent_effective = incoming * opponent_uptime
    candidate_ttk = Fraction(opponent.hitpoints + food_slots * heal_per_eat, 1) / candidate_effective
    opponent_ttk = Fraction(candidate.hitpoints + food_slots * heal_per_eat, 1) / opponent_effective
    if candidate_ttk == opponent_ttk:
        return Fraction(0)
    if candidate_ttk < opponent_ttk:
        return (opponent_ttk - candidate_ttk) * opponent_effective / heal_per_eat
    return -(candidate_ttk - opponent_ttk) * candidate_effective / heal_per_eat


def _race_scenarios(
    candidates: Sequence[RankingCandidate],
    panel: Sequence[RankingCandidate],
    *,
    self_matchup_reserve: RankingCandidate | None,
    eat_penalties: Sequence[int],
    food_slots: int,
    heal_per_eat: int,
    successful_zero_to_one: bool,
) -> tuple[tuple[RaceScenario, ...], ...]:
    results: list[tuple[RaceScenario, ...]] = []
    for candidate in candidates:
        opponents = [opponent for opponent in panel if opponent.candidate_id != candidate.candidate_id]
        # A panel member would otherwise receive a synthetic zero-margin mirror
        # while every outside row faces 32 distinct opponents.  Use one
        # deterministic ranking-only reserve so the real run compares every
        # row against the same number of non-self opponents.
        if (
            len(opponents) < len(panel)
            and self_matchup_reserve is not None
            and self_matchup_reserve.candidate_id != candidate.candidate_id
        ):
            opponents.append(self_matchup_reserve)
        if not opponents:
            # The one-row test/input case has no distinct opponent; its mirror
            # is the only defined neutral comparison.
            opponents.append(candidate)
        scenarios: list[RaceScenario] = []
        for eat_penalty in eat_penalties:
            margins = tuple(
                _race_margin(
                    candidate,
                    opponent,
                    eat_penalty=eat_penalty,
                    food_slots=food_slots,
                    heal_per_eat=heal_per_eat,
                    successful_zero_to_one=successful_zero_to_one,
                )
                for opponent in opponents
            )
            scenarios.append(
                RaceScenario(
                    eat_penalty=eat_penalty,
                    opponent_count=len(margins),
                    worst_margin_fish=min(margins),
                    tenth_percentile_margin_fish=_quantile(margins, 1, 10),
                    mean_margin_fish=_mean(margins),
                    win_fraction=Fraction(sum(value > 0 for value in margins), len(margins)),
                )
            )
        results.append(tuple(scenarios))
    return tuple(results)


def _midrank_percentiles(values: Sequence[Fraction]) -> tuple[Fraction, ...]:
    if len(values) == 1:
        return (Fraction(1),)
    ordered = sorted(values)
    denominator = 2 * (len(values) - 1)
    return tuple(
        Fraction(
            bisect_left(ordered, value) + bisect_right(ordered, value) - 1,
            denominator,
        )
        for value in values
    )


def _category_scores(
    candidates: Sequence[RankingCandidate],
    races: Sequence[tuple[RaceScenario, ...]],
) -> tuple[Mapping[str, Fraction], ...]:
    penalty_index = {scenario.eat_penalty: index for index, scenario in enumerate(races[0])}
    primary_index = penalty_index.get(3, 0)
    sensitivity_index = penalty_index.get(0, primary_index)
    robust_worst = tuple(min(scenario.worst_margin_fish for scenario in item) for item in races)
    metric_groups: Mapping[str, tuple[tuple[Fraction, ...], ...]] = {
        "sustain": tuple(
            tuple(candidate.sustained_dpt[index] for candidate in candidates) for index in range(len(DEFENCE_STATES))
        ),
        "race": (
            robust_worst,
            tuple(item[primary_index].tenth_percentile_margin_fish for item in races),
            tuple(item[primary_index].mean_margin_fish for item in races),
            tuple(item[sensitivity_index].mean_margin_fish for item in races),
        ),
        "burst": (
            *tuple(tuple(candidate.ko_by_window[index] for candidate in candidates) for index in range(len(WINDOWS))),
            tuple(Fraction(candidate.max_hit) for candidate in candidates),
            tuple(Fraction(candidate.potted_max_hit) for candidate in candidates),
        ),
        "defence": (
            *tuple(
                tuple(Fraction(candidate.defence_rolls[index]) for candidate in candidates)
                for index in range(len(DAMAGE_TYPES))
            ),
            tuple(Fraction(candidate.magic_defence_bonus) for candidate in candidates),
        ),
        "utility": (
            tuple(Fraction(candidate.maximum_range) for candidate in candidates),
            tuple(Fraction(len(candidate.styles)) for candidate in candidates),
            tuple(Fraction(candidate.prayer_level) for candidate in candidates),
            tuple(Fraction(candidate.prayer_bonus) for candidate in candidates),
            tuple(Fraction(candidate.magic_attack_bonus) for candidate in candidates),
        ),
    }
    totals = [{name: Fraction(0) for name in metric_groups} for _ in candidates]
    for category, metrics in metric_groups.items():
        for metric in metrics:
            for index, percentile in enumerate(_midrank_percentiles(metric)):
                totals[index][category] += percentile
        for index in range(len(candidates)):
            totals[index][category] /= len(metrics)
    return tuple(totals)


def _extreme_flags(
    candidates: Sequence[RankingCandidate],
    panel_reasons: Mapping[str, tuple[str, ...]],
) -> tuple[tuple[str, ...], ...]:
    metrics: Mapping[str, tuple[Fraction, ...]] = {
        "sustain_extreme": tuple(candidate.sustain_worst for candidate in candidates),
        "four_tick_ko_extreme": tuple(candidate.ko_by_window[0] for candidate in candidates),
        "twelve_tick_ko_extreme": tuple(candidate.ko_by_window[3] for candidate in candidates),
        "potted_max_hit_extreme": tuple(Fraction(candidate.potted_max_hit) for candidate in candidates),
        "physical_defence_extreme": tuple(candidate.physical_defence_average for candidate in candidates),
        "magic_defence_extreme": tuple(Fraction(candidate.magic_defence_bonus) for candidate in candidates),
        "magic_attack_gear_extreme": tuple(Fraction(candidate.magic_attack_bonus) for candidate in candidates),
        "range_extreme": tuple(Fraction(candidate.maximum_range) for candidate in candidates),
    }
    percentile_rows = {name: _midrank_percentiles(values) for name, values in metrics.items()}
    flags: list[tuple[str, ...]] = []
    for index, candidate in enumerate(candidates):
        current = {name for name, percentiles in percentile_rows.items() if percentiles[index] >= Fraction(99, 100)}
        for reason in panel_reasons.get(candidate.candidate_id, ()):
            if reason.startswith("damage_type_representative:"):
                current.add(reason)
        flags.append(tuple(sorted(current)))
    return tuple(flags)


def rank_survivor_manifest(
    path: str | Path,
    ruleset: Ruleset,
    *,
    panel_size: int = 32,
    food_slots: int = 28,
    heal_per_eat: int = 14,
    eat_penalties: Iterable[int] = DEFAULT_EAT_PENALTIES,
    preview_size: int = 50,
) -> SurvivorRankingReport:
    """Rank every resolved survivor without deleting any candidate.

    The result is a deterministic work-priority list.  Its notional attrition
    race and population-percentile composite are intentionally weaker evidence
    than the later tick simulator and policy/RL search.
    """
    if food_slots < 0:
        raise ValueError("food_slots cannot be negative")
    if panel_size < 1:
        raise ValueError("panel_size must be positive")
    if heal_per_eat <= 0:
        raise ValueError("heal_per_eat must be positive")
    if preview_size < 0:
        raise ValueError("preview_size cannot be negative")
    penalties = tuple(dict.fromkeys(int(value) for value in eat_penalties))
    if not penalties or any(value < 0 for value in penalties):
        raise ValueError("eat_penalties must contain non-negative integers")
    if not {0, 3} <= set(penalties):
        raise ValueError("eat_penalties must include the primary 3-tick and 0-tick sensitivity cases")

    candidates = load_ranking_candidates(path, ruleset)
    comparison_selection, all_panel_reasons = _select_panel(candidates, min(panel_size + 1, len(candidates)))
    actual_panel_size = min(panel_size, len(candidates))
    panel = comparison_selection[:actual_panel_size]
    self_matchup_reserve = (
        comparison_selection[actual_panel_size] if len(comparison_selection) > actual_panel_size else None
    )
    panel_reasons = {candidate.candidate_id: all_panel_reasons[candidate.candidate_id] for candidate in panel}
    zero_to_one = bool(ruleset.mechanics.require("damage.player_successful_zero_to_one").value)
    races = _race_scenarios(
        candidates,
        panel,
        self_matchup_reserve=self_matchup_reserve,
        eat_penalties=penalties,
        food_slots=food_slots,
        heal_per_eat=heal_per_eat,
        successful_zero_to_one=zero_to_one,
    )
    category_scores = _category_scores(candidates, races)
    niche_flags = _extreme_flags(candidates, panel_reasons)
    overall = tuple(_mean(tuple(scores.values())) for scores in category_scores)
    order = sorted(
        range(len(candidates)),
        key=lambda index: (
            -overall[index],
            -category_scores[index]["race"],
            -category_scores[index]["burst"],
            -category_scores[index]["sustain"],
            -category_scores[index]["defence"],
            -category_scores[index]["utility"],
            candidates[index].candidate_id,
        ),
    )
    count = len(candidates)
    s_cutoff = max(1, (count + 99) // 100)
    a_cutoff = max(s_cutoff, (count + 19) // 20)
    b_cutoff = max(a_cutoff, (count + 4) // 5)
    ranked_rows: list[RankedCandidate] = []
    for rank, index in enumerate(order, start=1):
        flags = niche_flags[index]
        seed_reasons = panel_reasons.get(candidates[index].candidate_id, ())
        if rank <= s_cutoff:
            tier = "S"
        elif rank <= a_cutoff:
            tier = "A"
        elif rank <= b_cutoff:
            tier = "B"
        elif flags or seed_reasons:
            tier = "N"
        else:
            tier = "C"
        strongest = sorted(
            category_scores[index],
            key=lambda name: (-category_scores[index][name], name),
        )[:2]
        reasons = tuple(f"strong_category:{name}" for name in strongest) + flags
        ranked_rows.append(
            RankedCandidate(
                candidate=candidates[index],
                rank=rank,
                tier=tier,
                overall_score=overall[index],
                category_scores=tuple(sorted(category_scores[index].items())),
                race_scenarios=races[index],
                niche_flags=flags,
                rank_reasons=reasons,
                simulator_seed_reasons=seed_reasons,
            )
        )
    return SurvivorRankingReport(
        input_path=str(Path(path)),
        rankings=tuple(ranked_rows),
        panel_candidate_ids=tuple(candidate.candidate_id for candidate in panel),
        panel_reasons=panel_reasons,
        ranking_self_matchup_reserve_candidate_id=(self_matchup_reserve.candidate_id if self_matchup_reserve else None),
        food_slots=food_slots,
        heal_per_eat=heal_per_eat,
        eat_penalties=penalties,
        preview_size=preview_size,
    )


def _ranked_document(ranked: RankedCandidate) -> Mapping[str, object]:
    candidate = ranked.candidate
    return {
        "rank": ranked.rank,
        "tier": ranked.tier,
        "candidate_id": candidate.candidate_id,
        "resolved_signature": candidate.resolved_signature,
        "overall_score": _fraction_document(ranked.overall_score),
        "category_scores": {name: _fraction_document(value) for name, value in ranked.category_scores},
        "race_scenarios": tuple(
            {
                "eat_penalty": scenario.eat_penalty,
                "opponent_count": scenario.opponent_count,
                "worst_margin_fish": _fraction_document(scenario.worst_margin_fish),
                "tenth_percentile_margin_fish": _fraction_document(scenario.tenth_percentile_margin_fish),
                "mean_margin_fish": _fraction_document(scenario.mean_margin_fish),
                "win_fraction": _fraction_document(scenario.win_fraction),
            }
            for scenario in ranked.race_scenarios
        ),
        "sustained_dpt": {
            state: _fraction_document(value)
            for state, value in zip(DEFENCE_STATES, candidate.sustained_dpt, strict=True)
        },
        "cadence_ko_by_window": {
            str(window): _fraction_document(value)
            for window, value in zip(WINDOWS, candidate.ko_by_window, strict=True)
        },
        "resolved_styles": tuple(
            {
                "style_id": style.style_id,
                "damage_type": style.damage_type,
                "attack_roll": style.attack_roll,
                "max_hit": style.max_hit,
                "potted_max_hit": style.potted_max_hit,
                "cooldown_ticks": style.cooldown_ticks,
                "maximum_range": style.maximum_range,
            }
            for style in candidate.styles
        ),
        "maximum_attack_roll": candidate.maximum_attack_roll,
        "max_hit": candidate.max_hit,
        "potted_max_hit": candidate.potted_max_hit,
        "maximum_range": candidate.maximum_range,
        "defence_rolls": dict(zip(DAMAGE_TYPES, candidate.defence_rolls, strict=True)),
        "niche_flags": ranked.niche_flags,
        "rank_reasons": ranked.rank_reasons,
        "simulator_seed_reasons": ranked.simulator_seed_reasons,
        "profile_id": candidate.profile_id,
        "levels": dict(
            zip(
                ("attack", "strength", "ranged", "magic", "prayer", "defence", "hitpoints"),
                candidate.levels,
                strict=True,
            )
        ),
        "weapon": {
            "name": candidate.weapon_name,
            "type": candidate.weapon_type,
            "slot": candidate.weapon_slot,
            "two_handed": candidate.two_handed,
        },
        "equipment_names": candidate.equipment_names,
    }


def enrich_ranked_survivor_csv(
    ranked_csv: str | Path,
    survivor_manifest: str | Path,
    output: str | Path,
) -> None:
    """Join ranking columns to every available static source/gear column.

    The source manifest is over 300 MB because each row contains a full KO
    probability document.  A temporary SQLite index keeps this join bounded in
    memory and lets the final CSV remain in rank order.
    """
    ranked_path = Path(ranked_csv)
    source_path = Path(survivor_manifest)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    database_path = destination.with_suffix(destination.suffix + ".source-index.tmp.sqlite3")
    temporary = destination.with_suffix(destination.suffix + ".enriched.tmp")
    database_path.unlink(missing_ok=True)
    temporary.unlink(missing_ok=True)

    connection = sqlite3.connect(database_path)
    try:
        with ranked_path.open(newline="", encoding="utf-8") as handle:
            ranked_reader = csv.DictReader(handle)
            ranked_fields = tuple(ranked_reader.fieldnames or ())
        if "candidate_id" not in ranked_fields:
            raise ValueError("Ranked CSV is missing candidate_id")

        with source_path.open(newline="", encoding="utf-8") as handle:
            source_reader = csv.DictReader(handle)
            source_header = tuple(source_reader.fieldnames or ())
            if "candidate_id" not in source_header:
                raise ValueError("Survivor manifest is missing candidate_id")
            source_fields = tuple(
                field for field in source_header if field not in ranked_fields and field not in _OMITTED_SOURCE_BLOBS
            )
            connection.execute("CREATE TABLE source_rows (candidate_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            batch: list[tuple[str, str]] = []
            source_count = 0
            for row in source_reader:
                candidate_id = row["candidate_id"]
                payload = json.dumps(
                    [row.get(field, "") for field in source_fields],
                    separators=(",", ":"),
                )
                batch.append((candidate_id, payload))
                source_count += 1
                if len(batch) >= 1_000:
                    connection.executemany("INSERT INTO source_rows(candidate_id, payload) VALUES (?, ?)", batch)
                    batch.clear()
            if batch:
                connection.executemany("INSERT INTO source_rows(candidate_id, payload) VALUES (?, ?)", batch)
            connection.commit()

        final_fields = (*ranked_fields, *source_fields)
        matched = 0
        with (
            ranked_path.open(newline="", encoding="utf-8") as ranked_handle,
            temporary.open("w", newline="", encoding="utf-8") as output_handle,
        ):
            ranked_reader = csv.DictReader(ranked_handle)
            writer = csv.DictWriter(output_handle, fieldnames=final_fields)
            writer.writeheader()
            for ranked_row in ranked_reader:
                found = connection.execute(
                    "SELECT payload FROM source_rows WHERE candidate_id = ?",
                    (ranked_row["candidate_id"],),
                ).fetchone()
                if found is None:
                    raise ValueError(
                        f"Ranked candidate {ranked_row['candidate_id']!r} is absent from survivor manifest"
                    )
                source_values = json.loads(found[0])
                writer.writerow(
                    {
                        **ranked_row,
                        **dict(zip(source_fields, source_values, strict=True)),
                    }
                )
                matched += 1
        if matched != source_count:
            raise ValueError(
                "Ranked CSV and survivor manifest candidate counts differ: "
                f"{matched} ranked versus {source_count} source"
            )
        temporary.replace(destination)
    finally:
        connection.close()
        database_path.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)


def write_ranked_survivors_csv(
    report: SurvivorRankingReport,
    output: str | Path,
) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".ranking-base.tmp")
    fieldnames = (
        "rank",
        "tier",
        "candidate_id",
        "resolved_signature",
        "overall_score",
        "overall_score_decimal",
        "sustain_score",
        "race_score",
        "burst_score",
        "defence_score",
        "utility_score",
        "race_penalty3_worst_fish",
        "race_penalty3_p10_fish",
        "race_penalty3_mean_fish",
        "race_penalty0_worst_fish",
        "race_penalty0_mean_fish",
        "dpt_low",
        "dpt_medium",
        "dpt_high",
        "ko_4_tick",
        "ko_5_tick",
        "ko_8_tick",
        "ko_12_tick",
        "maximum_attack_roll",
        "max_hit",
        "potted_max_hit",
        "maximum_range",
        "defence_stab_roll",
        "defence_slash_roll",
        "defence_crush_roll",
        "defence_ranged_roll",
        "magic_attack_bonus",
        "magic_defence_bonus",
        "prayer_bonus",
        "niche_flags",
        "rank_reasons",
        "simulator_seed",
        "simulator_seed_reasons",
        "profile_id",
        "account_attack",
        "account_strength",
        "account_ranged",
        "account_magic",
        "account_prayer",
        "account_defence",
        "account_hitpoints",
        "head_name",
        "neck_name",
        "body_name",
        "legs_name",
        "hands_name",
        "weapon_name",
        "ammo_name",
        "shield_name",
        "weapon_type",
        "weapon_slot",
        "two_handed",
        "damage_types",
        "style_ids",
    )
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for ranked in report.rankings:
            candidate = ranked.candidate
            categories = ranked.category_map
            race_by_penalty = {scenario.eat_penalty: scenario for scenario in ranked.race_scenarios}
            primary = race_by_penalty.get(3, ranked.race_scenarios[0])
            sensitivity = race_by_penalty.get(0, primary)
            writer.writerow(
                {
                    "rank": ranked.rank,
                    "tier": ranked.tier,
                    "candidate_id": candidate.candidate_id,
                    "resolved_signature": candidate.resolved_signature,
                    "overall_score": _fraction_text(ranked.overall_score),
                    "overall_score_decimal": f"{float(ranked.overall_score):.8f}",
                    "sustain_score": _fraction_text(categories["sustain"]),
                    "race_score": _fraction_text(categories["race"]),
                    "burst_score": _fraction_text(categories["burst"]),
                    "defence_score": _fraction_text(categories["defence"]),
                    "utility_score": _fraction_text(categories["utility"]),
                    "race_penalty3_worst_fish": _fraction_text(primary.worst_margin_fish),
                    "race_penalty3_p10_fish": _fraction_text(primary.tenth_percentile_margin_fish),
                    "race_penalty3_mean_fish": _fraction_text(primary.mean_margin_fish),
                    "race_penalty0_worst_fish": _fraction_text(sensitivity.worst_margin_fish),
                    "race_penalty0_mean_fish": _fraction_text(sensitivity.mean_margin_fish),
                    **{
                        f"dpt_{state}": _fraction_text(value)
                        for state, value in zip(DEFENCE_STATES, candidate.sustained_dpt, strict=True)
                    },
                    **{
                        f"ko_{window}_tick": _fraction_text(value)
                        for window, value in zip(WINDOWS, candidate.ko_by_window, strict=True)
                    },
                    "maximum_attack_roll": candidate.maximum_attack_roll,
                    "max_hit": candidate.max_hit,
                    "potted_max_hit": candidate.potted_max_hit,
                    "maximum_range": candidate.maximum_range,
                    **{
                        f"defence_{damage_type}_roll": value
                        for damage_type, value in zip(DAMAGE_TYPES, candidate.defence_rolls, strict=True)
                    },
                    "magic_attack_bonus": candidate.magic_attack_bonus,
                    "magic_defence_bonus": candidate.magic_defence_bonus,
                    "prayer_bonus": candidate.prayer_bonus,
                    "niche_flags": ";".join(ranked.niche_flags),
                    "rank_reasons": ";".join(ranked.rank_reasons),
                    "simulator_seed": bool(ranked.simulator_seed_reasons),
                    "simulator_seed_reasons": ";".join(ranked.simulator_seed_reasons),
                    "profile_id": candidate.profile_id,
                    **dict(
                        zip(
                            (
                                "account_attack",
                                "account_strength",
                                "account_ranged",
                                "account_magic",
                                "account_prayer",
                                "account_defence",
                                "account_hitpoints",
                            ),
                            candidate.levels,
                            strict=True,
                        )
                    ),
                    **dict(
                        zip(
                            (
                                "head_name",
                                "neck_name",
                                "body_name",
                                "legs_name",
                                "hands_name",
                                "weapon_name",
                                "ammo_name",
                                "shield_name",
                            ),
                            candidate.equipment_names,
                            strict=True,
                        )
                    ),
                    "weapon_type": candidate.weapon_type,
                    "weapon_slot": candidate.weapon_slot,
                    "two_handed": candidate.two_handed,
                    "damage_types": ";".join(candidate.damage_types),
                    "style_ids": ";".join(style.style_id for style in candidate.styles),
                }
            )
    try:
        enrich_ranked_survivor_csv(temporary, report.input_path, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_survivor_ranking_report(
    report: SurvivorRankingReport,
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
