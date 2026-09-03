from __future__ import annotations

import contextlib
import csv
import io
import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from pure_solver.cli import main
from pure_solver.ruleset import load_ruleset
from pure_solver.survivor_ranking import (
    DEFENCE_STATES,
    HP_THRESHOLDS,
    WINDOWS,
    load_ranking_candidates,
    rank_survivor_manifest,
    write_ranked_survivors_csv,
    write_survivor_ranking_report,
)

RULESET = load_ruleset("rulesets/osrs-f2p-v1")


def _fraction(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _row(
    candidate_id: str,
    *,
    dpt: Fraction = Fraction(1, 2),
    ko: Fraction = Fraction(1, 10),
    damage_type: str = "slash",
    style_id: str = "accurate_slash",
    maximum_range: int = 1,
    defence: int = 10,
    magic_defence: int = 0,
    weapon_type: str = "scimitar",
) -> dict[str, str]:
    styles = [
        {
            "style_id": style_id,
            "damage_type": damage_type,
            "attack_roll": 1_000,
            "max_hit": 5,
            "potted_max_hit": 6,
            "cooldown_ticks": 4,
            "maximum_range": maximum_range,
        }
    ]
    ko_document = {
        f"{state}:{window}:{hp}": _fraction(ko)
        for state in DEFENCE_STATES
        for window in WINDOWS
        for hp in HP_THRESHOLDS
    }
    return {
        "candidate_id": candidate_id,
        "resolved_signature": f"sig-{candidate_id}",
        "resolved_styles_json": json.dumps(styles),
        "best_expected_damage_per_tick_json": json.dumps({state: _fraction(dpt) for state in DEFENCE_STATES}),
        "cadence_ko_probabilities_json": json.dumps(ko_document),
        "cadence_ko_scope": "repeated_weapon_cooldown_only_no_projectile_delay_or_switching",
        "profile_id": "1",
        "account_attack": "20",
        "account_strength": "20",
        "account_ranged": "1" if damage_type != "ranged" else "20",
        "account_magic": "1",
        "account_prayer": "1",
        "account_defence": "1",
        "account_hitpoints": "10",
        "attack_magic": "0",
        "defence_stab": str(defence),
        "defence_slash": str(defence),
        "defence_crush": str(defence),
        "defence_magic": str(magic_defence),
        "defence_ranged": str(defence),
        "prayer": "0",
        "weapon_type": weapon_type,
        "weapon_name": f"Weapon {candidate_id}",
        "weapon_slot": "weapon",
        "two_handed": "false",
        "head_name": "Head",
        "head_id": "1001",
        "neck_name": "Neck",
        "body_name": "Body",
        "legs_name": "Legs",
        "hands_name": "Hands",
        "ammo_name": "",
        "shield_name": "Shield",
        "attack_stab": "17",
        "weapon_attack_speed": "4",
    }


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class SurvivorRankingTests(unittest.TestCase):
    def test_ranks_every_candidate_without_deletion_and_is_row_order_stable(self) -> None:
        rows = [
            _row("slow", dpt=Fraction(1, 3), ko=Fraction(1, 20)),
            _row("burst", dpt=Fraction(1, 3), ko=Fraction(4, 5)),
            _row(
                "range",
                dpt=Fraction(1, 3),
                ko=Fraction(1, 20),
                damage_type="ranged",
                style_id="rapid_ranged",
                maximum_range=8,
                weapon_type="shortbow",
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            left = Path(directory) / "left.csv"
            right = Path(directory) / "right.csv"
            _write(left, rows)
            _write(right, list(reversed(rows)))
            first = rank_survivor_manifest(left, RULESET, panel_size=3)
            second = rank_survivor_manifest(right, RULESET, panel_size=3)

        self.assertEqual(len(first.rankings), 3)
        self.assertEqual(first.to_document()["counts"]["candidates_removed_by_ranking"], 0)
        self.assertEqual(
            [item.candidate.candidate_id for item in first.rankings],
            [item.candidate.candidate_id for item in second.rankings],
        )
        self.assertEqual(first.rankings[0].candidate.candidate_id, "burst")
        self.assertTrue(all(isinstance(item.overall_score, Fraction) for item in first.rankings))

    def test_exact_fraction_difference_affects_order_before_candidate_id_tie_break(self) -> None:
        # These values round to the same short decimal, so a float-rounded
        # leaderboard could incorrectly fall back to candidate_id.
        lower = Fraction(10**18, 3 * 10**18 + 1)
        higher = Fraction(10**18 + 1, 3 * 10**18 + 3)
        self.assertGreater(higher, lower)
        rows = [_row("a-lower", dpt=lower), _row("z-higher", dpt=higher)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.csv"
            _write(path, rows)
            report = rank_survivor_manifest(path, RULESET, panel_size=2)
        self.assertEqual(report.rankings[0].candidate.candidate_id, "z-higher")

    def test_diverse_panel_forces_ranged_and_defence_specialists(self) -> None:
        rows = [
            _row("melee", dpt=Fraction(4, 5)),
            _row(
                "ranged",
                dpt=Fraction(1, 5),
                damage_type="ranged",
                style_id="rapid_ranged",
                maximum_range=8,
                weapon_type="shortbow",
            ),
            _row("tank", dpt=Fraction(1, 5), defence=40, magic_defence=20),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.csv"
            _write(path, rows)
            report = rank_survivor_manifest(path, RULESET, panel_size=3)
        self.assertEqual(set(report.panel_candidate_ids), {"melee", "ranged", "tank"})
        self.assertIn("damage_type_representative:ranged", report.panel_reasons["ranged"])
        self.assertTrue(
            any(
                reason in report.panel_reasons["tank"]
                for reason in ("physical_defence_extreme", "magic_defence_extreme")
            )
        )

    def test_panel_members_use_a_distinct_reserve_instead_of_self_matchup(self) -> None:
        rows = [
            _row("one", dpt=Fraction(1, 5)),
            _row("two", dpt=Fraction(2, 5)),
            _row("three", dpt=Fraction(3, 5)),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.csv"
            _write(path, rows)
            report = rank_survivor_manifest(path, RULESET, panel_size=2)

        self.assertIsNotNone(report.ranking_self_matchup_reserve_candidate_id)
        self.assertTrue(
            all(scenario.opponent_count == 2 for ranked in report.rankings for scenario in ranked.race_scenarios)
        )

    def test_rejects_bad_fraction_and_duplicate_candidate_id(self) -> None:
        malformed = _row("bad")
        malformed["best_expected_damage_per_tick_json"] = json.dumps(
            {state: {"numerator": 1} for state in DEFENCE_STATES}
        )
        with tempfile.TemporaryDirectory() as directory:
            bad_path = Path(directory) / "bad.csv"
            duplicate_path = Path(directory) / "duplicate.csv"
            _write(bad_path, [malformed])
            _write(duplicate_path, [_row("same"), _row("same")])
            with self.assertRaisesRegex(ValueError, "numerator and denominator"):
                load_ranking_candidates(bad_path, RULESET)
            with self.assertRaisesRegex(ValueError, "duplicate candidate"):
                load_ranking_candidates(duplicate_path, RULESET)

    def test_rejects_fractional_json_integer_instead_of_truncating_it(self) -> None:
        malformed = _row("bad-number")
        styles = json.loads(malformed["resolved_styles_json"])
        styles[0]["max_hit"] = 5.5
        malformed["resolved_styles_json"] = json.dumps(styles)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-number.csv"
            _write(path, [malformed])
            with self.assertRaisesRegex(ValueError, "max_hit must be an integer"):
                load_ranking_candidates(path, RULESET)

    def test_rejects_incompatible_cadence_ko_scope(self) -> None:
        malformed = _row("wrong-scope")
        malformed["cadence_ko_scope"] = "projectile_and_switch_stack"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong-scope.csv"
            _write(path, [malformed])
            with self.assertRaisesRegex(ValueError, "unsupported cadence KO scope"):
                load_ranking_candidates(path, RULESET)

    def test_writers_preserve_all_rows_and_report_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.csv"
            ranked_path = Path(directory) / "ranked.csv"
            report_path = Path(directory) / "report.json"
            _write(input_path, [_row("one"), _row("two", ko=Fraction(1, 2))])
            report = rank_survivor_manifest(input_path, RULESET, panel_size=2)
            write_ranked_survivors_csv(report, ranked_path)
            write_survivor_ranking_report(report, report_path)
            ranked_rows = list(csv.DictReader(ranked_path.open(encoding="utf-8")))
            document = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(len(ranked_rows), 2)
        self.assertEqual(ranked_rows[0]["head_id"], "1001")
        self.assertEqual(ranked_rows[0]["attack_stab"], "17")
        self.assertEqual(ranked_rows[0]["weapon_attack_speed"], "4")
        self.assertIn("resolved_styles_json", ranked_rows[0])
        self.assertEqual(document["counts"]["input_candidates"], 2)
        self.assertEqual(document["counts"]["ranked_candidates"], 2)
        self.assertFalse(document["verification"]["deletes_candidates"])
        self.assertFalse(document["verification"]["perfect_play_claim"])

    def test_cli_writes_ranked_csv_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.csv"
            ranked_path = Path(directory) / "ranked.csv"
            report_path = Path(directory) / "report.json"
            _write(input_path, [_row("one"), _row("two", ko=Fraction(1, 2))])
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status = main(
                    [
                        "rank-resolved-survivors",
                        "rulesets/osrs-f2p-v1",
                        str(input_path),
                        "--ranked-output",
                        str(ranked_path),
                        "--report-output",
                        str(report_path),
                        "--panel-size",
                        "2",
                    ]
                )
            summary = json.loads(stdout.getvalue())
            ranked_exists = ranked_path.exists()
            report_exists = report_path.exists()

        self.assertEqual(status, 0)
        self.assertEqual(summary["ranked_candidates"], 2)
        self.assertEqual(summary["candidates_removed_by_ranking"], 0)
        self.assertTrue(ranked_exists)
        self.assertTrue(report_exists)


if __name__ == "__main__":
    unittest.main()
