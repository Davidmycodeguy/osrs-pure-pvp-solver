import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from pure_solver.accounts import AccountSearchBounds, LevelRange
from pure_solver.cli import main
from pure_solver.gear_matrix import (
    build_exact_account_gear_matrix,
    build_verified_gear_matrix,
    write_verified_gear_matrix_csv,
    write_verified_gear_matrix_json,
)
from pure_solver.legality import EquipmentItem
from pure_solver.ruleset import load_ruleset

RULESET = load_ruleset("rulesets/osrs-f2p-v1")


def _item(
    item_id: int,
    name: str,
    slot: str,
    *,
    requirements: dict[str, int] | None = None,
    bonuses: dict[str, int] | None = None,
    weapon_type: str | None = None,
    attack_speed: int | None = None,
    attack_range: int | None = None,
    attack_styles: tuple[str, ...] = (),
    ammo_ids: tuple[int, ...] = (),
    two_handed: bool = False,
) -> EquipmentItem:
    return EquipmentItem.from_document(
        {
            "item_id": item_id,
            "name": name,
            "free_to_play": True,
            "members": False,
            "obtainable": True,
            "slot": slot,
            "requirements": requirements or {},
            "bonuses": bonuses or {},
            "quest_requirements": [],
            "two_handed": two_handed,
            "weapon_type": weapon_type,
            "attack_speed": attack_speed,
            "attack_range": attack_range,
            "attack_styles": list(attack_styles),
            "ammo_ids": list(ammo_ids),
            "spell_ids": [],
            "mechanic_flags": [],
            "source_ids": ["fixture"],
            "status": "verified",
            "availability_scope": "f2p_standard_world",
        }
    )


class GearMatrixTests(unittest.TestCase):
    def test_matrix_derives_best_ammo_and_correct_shield(self) -> None:
        items = [
            _item(1, "Hat", "head"),
            _item(2, "Amulet", "neck"),
            _item(3, "Body", "body"),
            _item(4, "Legs", "legs"),
            _item(5, "Gloves", "hands"),
            _item(
                6,
                "Crossbow",
                "weapon",
                weapon_type="crossbow",
                attack_speed=5,
                attack_range=7,
                attack_styles=("rapid",),
                ammo_ids=(10,),
            ),
            _item(
                7,
                "Shortbow",
                "2h",
                weapon_type="shortbow",
                attack_speed=4,
                attack_range=7,
                attack_styles=("rapid",),
                ammo_ids=(11, 12),
                two_handed=True,
            ),
            _item(8, "Mooleta", "shield", bonuses={"defence_stab": 4}),
            _item(10, "Bronze bolts", "ammo", bonuses={"attack_ranged": 10, "ranged_strength": 10}),
            _item(11, "Bronze arrow", "ammo", bonuses={"attack_ranged": 7, "ranged_strength": 7}),
            _item(12, "Adamant arrow", "ammo", bonuses={"attack_ranged": 31, "ranged_strength": 31}),
        ]

        matrix = build_verified_gear_matrix(items, maximum_level=1)

        self.assertEqual(matrix.profile_count, 1)
        self.assertEqual(matrix.combination_count, 2)

        combos_by_weapon = {row.item_names["weapon"]: row for row in matrix.profiles[0].combinations}
        crossbow = combos_by_weapon["Crossbow"]
        shortbow = combos_by_weapon["Shortbow"]

        self.assertEqual(crossbow.item_names["ammo"], "Bronze bolts")
        self.assertEqual(crossbow.item_names["shield"], "Mooleta")
        self.assertEqual(shortbow.item_names["ammo"], "Adamant arrow")
        self.assertEqual(shortbow.item_names["shield"], "EMPTY")

        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "matrix.json"
            csv_path = Path(directory) / "matrix.csv"
            write_verified_gear_matrix_json(matrix, json_path)
            write_verified_gear_matrix_csv(matrix, csv_path)
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))

        self.assertEqual(payload["combination_count"], 2)
        self.assertEqual(rows[0]["shield_name"] in {"Mooleta", "EMPTY"}, True)
        self.assertIn("account_attack", rows[0])
        self.assertIn("req_defence", rows[0])

    def test_exact_account_matrix_uses_achievable_hitpoints_instead_of_placeholder_ten(self) -> None:
        items = [
            _item(1, "Hat", "head"),
            _item(2, "Amulet", "neck"),
            _item(3, "Body", "body"),
            _item(4, "Legs", "legs"),
            _item(5, "Gloves", "hands"),
            _item(
                6,
                "Shortbow",
                "2h",
                weapon_type="shortbow",
                attack_speed=4,
                attack_range=7,
                attack_styles=("accurate_ranged",),
                ammo_ids=(7,),
                two_handed=True,
            ),
            _item(7, "Mithril arrow", "ammo", bonuses={"ranged_strength": 22}),
        ]
        bounds = AccountSearchBounds(
            attack=LevelRange(1, 1),
            strength=LevelRange(1, 1),
            ranged=LevelRange(44, 44),
            magic=LevelRange(1, 1),
            prayer=LevelRange(8, 8),
            hitpoints=LevelRange(10, 99),
            combat_minimum=30,
            combat_maximum=30,
        )

        matrix = build_exact_account_gear_matrix(
            items,
            RULESET.mechanics,
            bounds,
            account_mode="f2p_standard_training",
        )

        self.assertEqual(matrix.profile_count, 1)
        self.assertEqual(matrix.combination_count, 1)
        profile = matrix.profiles[0]
        self.assertEqual(profile.account.hitpoints_level, 33)
        self.assertEqual(profile.level_minimums["ranged"], 44)
        self.assertEqual(profile.level_maximums["ranged"], 44)
        self.assertEqual(profile.combinations[0].account.hitpoints_level, 33)

    def test_cli_exports_exact_account_matrix_with_exact_levels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "matrix.json"
            csv_path = Path(directory) / "matrix.csv"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                status = main(
                    [
                        "export-exact-gear-matrix",
                        "rulesets/osrs-f2p-v1",
                        "--attack-min",
                        "1",
                        "--attack-max",
                        "1",
                        "--strength-min",
                        "1",
                        "--strength-max",
                        "1",
                        "--ranged-min",
                        "44",
                        "--ranged-max",
                        "44",
                        "--magic-min",
                        "1",
                        "--magic-max",
                        "1",
                        "--prayer-min",
                        "8",
                        "--prayer-max",
                        "8",
                        "--hitpoints-min",
                        "10",
                        "--hitpoints-max",
                        "99",
                        "--combat-min",
                        "30",
                        "--combat-max",
                        "30",
                        "--json-output",
                        str(json_path),
                        "--csv-output",
                        str(csv_path),
                    ]
                )
            summary = json.loads(stdout.getvalue())
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))

        self.assertEqual(status, 0)
        self.assertEqual(summary["profile_count"], 1)
        self.assertGreater(summary["combination_count"], 0)
        self.assertEqual(payload["profiles"][0]["account"]["hitpoints"], 33)
        self.assertEqual(rows[0]["account_hitpoints"], "33")
        self.assertEqual(rows[0]["ranged_min"], "44")
        self.assertEqual(rows[0]["ranged_max"], "44")


if __name__ == "__main__":
    unittest.main()
