"""Export the ranked CSVs into compact, dictionary-encoded browser datasets.

Usage: python scripts/export_build_data.py [combat_level] [cap]   (default 30, cap 250000; cap 0 = everything)

* ``builds.json`` — Stage 4 ranked survivors in rank order (when kits exist, only the builds
                    those kits reference; row index is not rank - 1).
* ``kits.json``   — one row per Stage 5 kit, linked to its build by row index;
                    fetched by the viewer right after builds.json.
"""

from __future__ import annotations

import csv
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEVEL = int(sys.argv[1]) if len(sys.argv) > 1 else 30
INPUT = ROOT / "outputs" / f"cb{LEVEL}-rust" / f"resolved-ranked-cb{LEVEL}.csv"
KITS_INPUT = ROOT / "outputs" / f"cb{LEVEL}-rust" / f"kits-cb{LEVEL}.csv"
DATA_DIR = Path(__file__).resolve().parents[1] / "public" / "data"
OUTPUT = DATA_DIR / f"builds-{LEVEL}.json"
KITS_OUTPUT = DATA_DIR / f"kits-{LEVEL}.json"
SCALE = 1_000_000
KIT_SCALE = 10_000

FIELDS = (
    "rank", "tier", "score", "profile_id",
    "attack", "strength", "ranged", "magic", "prayer_level", "defence_level", "hitpoints",
    "head", "neck", "body", "legs", "hands", "weapon", "ammo", "shield", "weapon_type",
    "head_id", "neck_id", "body_id", "legs_id", "hands_id", "weapon_id", "ammo_id", "shield_id",
    "maximum_attack_roll", "max_hit", "potted_max_hit", "maximum_range",
    "attack_stab", "attack_slash", "attack_crush", "attack_magic", "attack_ranged",
    "defence_stab", "defence_slash", "defence_crush", "defence_magic", "defence_ranged",
    "defence_stab_roll", "defence_slash_roll", "defence_crush_roll", "defence_ranged_roll",
    "melee_strength", "ranged_strength", "magic_damage", "prayer_bonus",
    "weapon_speed", "weapon_base_range", "weapon_styles", "two_handed",
    "dpt_low", "dpt_medium", "dpt_high", "ko_4", "ko_5", "ko_8", "ko_12",
    "sustain_score", "race_score", "burst_score", "defence_score", "utility_score",
    "niche_flags", "rank_reasons", "simulator_seed", "simulator_seed_reasons", "candidate_id",
    "req_attack", "req_strength", "req_ranged",
)

# Kit rows are small on purpose: 918k rows must stay loadable in a browser tab.
KIT_FIELDS = (
    "build", "rank", "tier", "baseline",
    "ko_weapon", "ko_weapon_id", "ko_max_hit", "ko_attack_roll", "ko_cooldown", "switch_slots", "food_slots",
    "score", "race_score", "ko_switch_score",
    "stack_15", "stack_20", "stack_30",
    "switch_ko_4", "switch_ko_5", "switch_ko_8", "switch_ko_12",
    "race_p3_mean_fish",
    "pressure", "bite", "finish_10", "finish_15", "finish_20", "pressure_rank",
    "potions", "max_burst", "ko_neck",
    "spell", "spell_max_hit", "rune_slots",
)


class Interner:
    def __init__(self) -> None:
        self.strings = [""]
        self.index = {"": 0}

    def __call__(self, value: str | None) -> int:
        text = value or ""
        found = self.index.get(text)
        if found is not None:
            return found
        found = len(self.strings)
        self.strings.append(text)
        self.index[text] = found
        return found


def integer(row: dict[str, str], name: str, default: int = 0) -> int:
    value = row.get(name, "")
    return int(value) if value not in (None, "") else default


def scaled_fraction(value: str, scale: int = SCALE) -> int:
    return round(float(Fraction(value)) * scale)


def build_row(row: dict[str, str], intern: Interner) -> list[int]:
    return [
        integer(row, "rank"), intern(row["tier"]), round(float(row["overall_score_decimal"]) * SCALE),
        integer(row, "profile_id"),
        integer(row, "account_attack"), integer(row, "account_strength"),
        integer(row, "account_ranged"), integer(row, "account_magic"),
        integer(row, "account_prayer"), integer(row, "account_defence"),
        integer(row, "account_hitpoints"),
        intern(row.get("head_name")), intern(row.get("neck_name")), intern(row.get("body_name")),
        intern(row.get("legs_name")), intern(row.get("hands_name")), intern(row.get("weapon_name")),
        intern(row.get("ammo_name")), intern(row.get("shield_name")), intern(row.get("weapon_type")),
        integer(row, "head_id", -1), integer(row, "neck_id", -1), integer(row, "body_id", -1),
        integer(row, "legs_id", -1), integer(row, "hands_id", -1), integer(row, "weapon_id", -1),
        integer(row, "ammo_id", -1), integer(row, "shield_id", -1),
        integer(row, "maximum_attack_roll"), integer(row, "max_hit"),
        integer(row, "potted_max_hit"), integer(row, "maximum_range"),
        integer(row, "attack_stab"), integer(row, "attack_slash"), integer(row, "attack_crush"),
        integer(row, "attack_magic"), integer(row, "attack_ranged"),
        integer(row, "defence_stab"), integer(row, "defence_slash"), integer(row, "defence_crush"),
        integer(row, "defence_magic"), integer(row, "defence_ranged"),
        integer(row, "defence_stab_roll"), integer(row, "defence_slash_roll"),
        integer(row, "defence_crush_roll"), integer(row, "defence_ranged_roll"),
        integer(row, "melee_strength"), integer(row, "ranged_strength"),
        integer(row, "magic_damage"), integer(row, "prayer"),
        integer(row, "weapon_attack_speed"), integer(row, "weapon_attack_range"),
        intern(row.get("weapon_attack_styles")), 1 if row.get("two_handed", "").lower() == "true" else 0,
        scaled_fraction(row["dpt_low"]), scaled_fraction(row["dpt_medium"]),
        scaled_fraction(row["dpt_high"]), scaled_fraction(row["ko_4_tick"]),
        scaled_fraction(row["ko_5_tick"]), scaled_fraction(row["ko_8_tick"]),
        scaled_fraction(row["ko_12_tick"]), scaled_fraction(row["sustain_score"]),
        scaled_fraction(row["race_score"]), scaled_fraction(row["burst_score"]),
        scaled_fraction(row["defence_score"]), scaled_fraction(row["utility_score"]),
        intern(row.get("niche_flags")), intern(row.get("rank_reasons")),
        1 if row.get("simulator_seed", "").lower() == "true" else 0,
        intern(row.get("simulator_seed_reasons")), intern(row["candidate_id"][:16]),
        integer(row, "req_attack"), integer(row, "req_strength"), integer(row, "req_ranged"),
    ]


def kit_row(row: dict[str, str], build_index: int, intern: Interner) -> list[int]:
    baseline = row["is_baseline"].lower() == "true"
    return [
        build_index, integer(row, "rank"), intern(row["tier"]), 1 if baseline else 0,
        intern("" if baseline else row["ko_weapon_name"]), integer(row, "ko_weapon_id", -1),
        integer(row, "ko_max_hit"), integer(row, "ko_attack_roll"), integer(row, "ko_cooldown_ticks"),
        integer(row, "switch_slots"), integer(row, "food_slots"),
        round(float(row["overall_score_decimal"]) * KIT_SCALE),
        scaled_fraction(row["race_score"], KIT_SCALE), scaled_fraction(row["ko_switch_score"], KIT_SCALE),
        scaled_fraction(row["stack_ko_15"], KIT_SCALE), scaled_fraction(row["stack_ko_20"], KIT_SCALE),
        scaled_fraction(row["stack_ko_30"], KIT_SCALE),
        scaled_fraction(row["switch_ko_4_tick"], KIT_SCALE), scaled_fraction(row["switch_ko_5_tick"], KIT_SCALE),
        scaled_fraction(row["switch_ko_8_tick"], KIT_SCALE), scaled_fraction(row["switch_ko_12_tick"], KIT_SCALE),
        scaled_fraction(row["race_penalty3_mean_fish"], 100),
        scaled_fraction(row["kill_pressure"], KIT_SCALE), scaled_fraction(row["kill_bite"], 100),
        scaled_fraction(row["finish_10"], KIT_SCALE), scaled_fraction(row["finish_15"], KIT_SCALE),
        scaled_fraction(row["finish_20"], KIT_SCALE), integer(row, "pressure_rank"),
        integer(row, "strength_potions"), integer(row, "max_burst"), intern(row.get("ko_neck_name")),
        intern(row.get("spell_name")), integer(row, "spell_max_hit"), integer(row, "rune_slots"),
    ]


def write_json(path: Path, document: dict) -> None:
    """Writes path and path + '.gz' (the viewer reads the JSON; the .gz is the release asset)."""
    import gzip
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    text = json.dumps(document, separators=(",", ":"))
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(text)
    gz_temporary = path.with_suffix(".json.gz.tmp")
    with gzip.open(gz_temporary, "wb", compresslevel=6) as handle:
        handle.write(text.encode("utf-8"))
    replace_with_retry(gz_temporary, path.with_suffix(".json.gz"))
    replace_with_retry(temporary, path)


def replace_with_retry(temporary: Path, path: Path) -> None:
    import time
    for attempt in range(20):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(3)  # the dev server may be streaming the old file; wait it out


def export_builds(keep: set[str] | None = None) -> dict[str, int]:
    """Builds in rank order; when `keep` is given only those candidate ids are written (row index != rank - 1 then)."""
    intern = Interner()
    rows: list[list[int]] = []
    tier_counts: dict[str, int] = {}
    build_index: dict[str, int] = {}
    with INPUT.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if keep is not None and row["candidate_id"] not in keep:
                continue
            tier_counts[row["tier"]] = tier_counts.get(row["tier"], 0) + 1
            build_index[row["candidate_id"]] = len(rows)
            rows.append(build_row(row, intern))
    if any(len(row) != len(FIELDS) for row in rows):
        raise RuntimeError("Viewer row schema length mismatch")
    document = {
        "version": 2,
        "count": len(rows),
        "fields": FIELDS,
        "strings": intern.strings,
        "rows": rows,
        "tierCounts": tier_counts,
    }
    write_json(OUTPUT, document)
    summary = {
        "output": str(OUTPUT),
        "rows": len(rows),
        "strings": len(intern.strings),
        "bytes": OUTPUT.stat().st_size,
    }
    print(json.dumps(summary))
    return build_index


# Browser cap: keep the top slice of BOTH rankings (plus every kit of any build in that
# slice, so the panel's "all KO options" list stays complete), and drop rune variants that
# do not out-pressure their no-runes twin.  0 disables the cap.
CAP = int(sys.argv[2]) if len(sys.argv) > 2 else 250_000


def fraction_value(text: str) -> float:
    return float(Fraction(text)) if text not in (None, "") else 0.0


def select_kits() -> tuple[set[int], dict[str, int], set[str]]:
    """Row numbers (0-based, CSV order) to export, counts for the summary, and the builds they use."""
    rows: list[tuple[int, int, str, str, float]] = []
    twins: dict[tuple[str, str, str], float] = {}
    with KITS_INPUT.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row["candidate_id"], row.get("ko_weapon_id", ""), row.get("ko_neck_id", ""))
            spell = row.get("spell_name", "")
            pressure = fraction_value(row["kill_pressure"])
            if not spell:
                twins[key] = pressure
            rows.append((int(row["rank"]), int(row["pressure_rank"]), row["candidate_id"], spell, pressure))
    counts = {"csv_rows": len(rows)}
    kept: list[int] = []
    with KITS_INPUT.open(newline="", encoding="utf-8") as handle:
        for line, row in enumerate(csv.DictReader(handle)):
            rank, pressure_rank, candidate, spell, pressure = rows[line]
            if spell:
                key = (candidate, row.get("ko_weapon_id", ""), row.get("ko_neck_id", ""))
                if pressure <= twins.get(key, -1.0):
                    continue
            kept.append(line)
    counts["after_rune_twin_filter"] = len(kept)
    if CAP <= 0:
        return set(kept), counts, {rows[line][2] for line in kept}
    slice_builds: set[str] = set()
    for line in kept:
        rank, pressure_rank, candidate, _, _ = rows[line]
        if rank <= CAP or pressure_rank <= CAP:
            slice_builds.add(candidate)
    selected = {line for line in kept if rows[line][2] in slice_builds}
    counts["cap"] = CAP
    counts["builds_in_slice"] = len(slice_builds)
    counts["exported"] = len(selected)
    return selected, counts, slice_builds


def export_kits(build_index: dict[str, int], selected: set[int], counts: dict[str, int]) -> None:
    intern = Interner()
    rows: list[list[int]] = []
    tier_counts: dict[str, int] = {}
    with KITS_INPUT.open(newline="", encoding="utf-8") as handle:
        for line, row in enumerate(csv.DictReader(handle)):
            if line not in selected:
                continue
            index = build_index.get(row["candidate_id"])
            if index is None:
                raise RuntimeError(
                    f"Kit {row['rank']} references candidate {row['candidate_id']} absent from the ranked builds"
                )
            tier_counts[row["tier"]] = tier_counts.get(row["tier"], 0) + 1
            rows.append(kit_row(row, index, intern))
    if any(len(row) != len(KIT_FIELDS) for row in rows):
        raise RuntimeError("Viewer kit schema length mismatch")
    document = {
        "version": 1,
        "count": len(rows),
        "scale": KIT_SCALE,
        "fields": KIT_FIELDS,
        "strings": intern.strings,
        "rows": rows,
        "tierCounts": tier_counts,
        "selection": counts,
    }
    write_json(KITS_OUTPUT, document)
    summary = {
        "output": str(KITS_OUTPUT),
        "rows": len(rows),
        "selection": counts,
        "strings": len(intern.strings),
        "bytes": KITS_OUTPUT.stat().st_size,
    }
    print(json.dumps(summary))


def main() -> None:
    if not KITS_INPUT.exists():
        export_builds()
        print(json.dumps({"kits": "skipped", "missing": str(KITS_INPUT)}))
        return
    selected, counts, builds = select_kits()
    export_kits(export_builds(builds), selected, counts)


if __name__ == "__main__":
    main()
