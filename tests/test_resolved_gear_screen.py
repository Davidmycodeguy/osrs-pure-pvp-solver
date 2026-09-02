import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from pure_solver.cli import main
from pure_solver.gear_catalog_export import BONUS_COLUMNS
from pure_solver.resolved_gear_screen import (
    screen_resolved_gear_matrix_csv,
    write_resolved_survivor_manifest,
)
from pure_solver.ruleset import load_ruleset

RULESET = load_ruleset("rulesets/osrs-f2p-v1")


class ResolvedGearScreenTests(unittest.TestCase):
    def _fixture(self, path: Path, *, reverse: bool = False) -> None:
        fieldnames = [
            "profile_id",
            "attack_min",
            "attack_max",
            "strength_min",
            "strength_max",
            "ranged_min",
            "ranged_max",
            "magic_min",
            "magic_max",
            "prayer_min",
            "prayer_max",
            "account_attack",
            "account_strength",
            "account_ranged",
            "account_magic",
            "account_prayer",
            "account_defence",
            "account_hitpoints",
            *(
                f"{slot}_{suffix}"
                for slot in ("head", "neck", "body", "legs", "hands", "weapon", "ammo", "shield")
                for suffix in ("id", "name")
            ),
            *BONUS_COLUMNS,
            "weapon_type",
            "weapon_attack_speed",
            "weapon_attack_range",
            "weapon_attack_styles",
            "two_handed",
        ]

        def row(head_id: int, name: str, slash: int, defence: int) -> dict[str, object]:
            result: dict[str, object] = {column: 0 for column in fieldnames}
            result.update(
                {
                    "profile_id": 1,
                    "attack_min": 40,
                    "attack_max": 40,
                    "strength_min": 40,
                    "strength_max": 40,
                    "ranged_min": 1,
                    "ranged_max": 1,
                    "magic_min": 1,
                    "magic_max": 1,
                    "prayer_min": 1,
                    "prayer_max": 1,
                    "account_attack": 40,
                    "account_strength": 40,
                    "account_ranged": 1,
                    "account_magic": 1,
                    "account_prayer": 1,
                    "account_defence": 1,
                    "account_hitpoints": 40,
                    "head_id": head_id,
                    "head_name": name,
                    "neck_id": 1731,
                    "neck_name": "Amulet of power",
                    "body_id": 577,
                    "body_name": "Blue wizard robe",
                    "legs_id": 542,
                    "legs_name": "Monk's robe",
                    "hands_id": 1063,
                    "hands_name": "Leather vambraces",
                    "weapon_id": 1333,
                    "weapon_name": "Rune scimitar",
                    "ammo_id": "",
                    "ammo_name": "EMPTY",
                    "shield_id": "",
                    "shield_name": "EMPTY",
                    "attack_slash": slash,
                    "defence_stab": defence,
                    "defence_slash": defence,
                    "defence_crush": defence,
                    "defence_ranged": defence,
                    "melee_strength": slash,
                    "weapon_type": "sword",
                    "weapon_attack_speed": 4,
                    "weapon_attack_range": 1,
                    "weapon_attack_styles": "accurate_slash;aggressive_slash;defensive_slash",
                    "two_handed": "False",
                }
            )
            return result

        rows = [row(579, "Blue wizard hat", 1, 1), row(12727, "Shaman mask", 3, 3)]
        if reverse:
            rows.reverse()
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_resolved_screen_prunes_exactly_dominated_row_and_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            matrix = Path(directory) / "matrix.csv"
            manifest = Path(directory) / "survivors.csv"
            self._fixture(matrix)
            report = screen_resolved_gear_matrix_csv(matrix, RULESET)
            write_resolved_survivor_manifest(report, manifest)
            rows = list(csv.DictReader(manifest.open(encoding="utf-8")))
        self.assertEqual(report.reduction.counts.starting_candidates, 2)
        self.assertEqual(report.reduction.counts.dominated_candidates_removed, 1)
        self.assertEqual(report.reduction.counts.remaining_pareto_candidates, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["head_name"], "Shaman mask")

    def test_manifest_is_stable_under_input_row_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            left = Path(directory) / "left.csv"
            right = Path(directory) / "right.csv"
            left_manifest = Path(directory) / "left-survivors.csv"
            right_manifest = Path(directory) / "right-survivors.csv"
            self._fixture(left)
            self._fixture(right, reverse=True)
            write_resolved_survivor_manifest(screen_resolved_gear_matrix_csv(left, RULESET), left_manifest)
            write_resolved_survivor_manifest(screen_resolved_gear_matrix_csv(right, RULESET), right_manifest)
            self.assertEqual(left_manifest.read_bytes(), right_manifest.read_bytes())

    def test_cli_writes_report_and_complete_survivor_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            matrix = Path(directory) / "matrix.csv"
            manifest = Path(directory) / "survivors.csv"
            report = Path(directory) / "report.json"
            self._fixture(matrix)
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "screen-resolved-gear-matrix",
                        "rulesets/osrs-f2p-v1",
                        str(matrix),
                        "--manifest-output",
                        str(manifest),
                        "--report-output",
                        str(report),
                    ]
                )
            summary = json.loads(output.getvalue())
            report_document = json.loads(report.read_text(encoding="utf-8"))
            survivor_rows = list(csv.DictReader(manifest.open(encoding="utf-8")))

        self.assertEqual(status, 0)
        self.assertEqual(summary["remaining_resolved_options"], 1)
        self.assertEqual(report_document["counts"]["remaining_resolved_options"], 1)
        self.assertEqual(len(survivor_rows), 1)
        self.assertEqual(
            survivor_rows[0]["cadence_ko_scope"],
            "repeated_weapon_cooldown_only_no_projectile_delay_or_switching",
        )


if __name__ == "__main__":
    unittest.main()
