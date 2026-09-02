import csv
import tempfile
import unittest
from pathlib import Path

from pure_solver.gear_catalog_export import BONUS_COLUMNS
from pure_solver.gear_screen import screen_gear_matrix_csv
from pure_solver.legality import EquipmentItem


def _item(item_id: int, name: str, slot: str, **extra: object) -> EquipmentItem:
    return EquipmentItem.from_document(
        {
            "item_id": item_id,
            "name": name,
            "free_to_play": True,
            "members": False,
            "obtainable": True,
            "slot": slot,
            "requirements": {},
            "bonuses": {},
            "quest_requirements": [],
            "two_handed": False,
            "weapon_type": None,
            "attack_speed": None,
            "attack_range": None,
            "attack_styles": [],
            "ammo_ids": [],
            "spell_ids": [],
            "mechanic_flags": [],
            "source_ids": ["fixture"],
            "status": "verified",
            "availability_scope": "f2p_standard_world",
            **extra,
        }
    )


class GearMatrixScreenTests(unittest.TestCase):
    def test_screen_reports_simulator_seed_count_and_safe_dominance(self) -> None:
        items = [
            _item(1, "Hat A", "head"),
            _item(2, "Hat B", "head"),
            _item(3, "Amulet", "neck"),
            _item(4, "Body", "body"),
            _item(5, "Legs", "legs"),
            _item(6, "Hands", "hands"),
            _item(
                7,
                "Sword",
                "weapon",
                weapon_type="sword",
                attack_speed=4,
                attack_range=1,
                attack_styles=["accurate_stab"],
            ),
        ]
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

        def row(head_id: int, head_name: str, attack_stab: int) -> dict[str, object]:
            result: dict[str, object] = {column: 0 for column in fieldnames}
            result.update(
                {
                    "profile_id": 1,
                    "attack_min": 1,
                    "attack_max": 30,
                    "strength_min": 1,
                    "strength_max": 30,
                    "ranged_min": 1,
                    "ranged_max": 30,
                    "magic_min": 1,
                    "magic_max": 30,
                    "prayer_min": 1,
                    "prayer_max": 30,
                    "account_attack": 1,
                    "account_strength": 1,
                    "account_ranged": 1,
                    "account_magic": 1,
                    "account_prayer": 1,
                    "account_defence": 1,
                    "account_hitpoints": 10,
                    "head_id": head_id,
                    "head_name": head_name,
                    "neck_id": 3,
                    "neck_name": "Amulet",
                    "body_id": 4,
                    "body_name": "Body",
                    "legs_id": 5,
                    "legs_name": "Legs",
                    "hands_id": 6,
                    "hands_name": "Hands",
                    "weapon_id": 7,
                    "weapon_name": "Sword",
                    "ammo_id": "",
                    "ammo_name": "EMPTY",
                    "shield_id": "",
                    "shield_name": "EMPTY",
                    "attack_stab": attack_stab,
                    "weapon_type": "sword",
                    "weapon_attack_speed": 4,
                    "weapon_attack_range": 1,
                    "weapon_attack_styles": "accurate_stab",
                    "two_handed": "False",
                }
            )
            return result

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matrix.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(row(1, "Hat A", 1))
                writer.writerow(row(2, "Hat B", 2))
            report = screen_gear_matrix_csv(path, items, seed_size=1)

        document = report.to_document()
        self.assertEqual(document["counts"]["starting_candidates"], 2)
        self.assertEqual(document["counts"]["dominated_candidates_removed"], 1)
        self.assertEqual(document["counts"]["remaining_pareto_candidates"], 1)
        self.assertEqual(document["counts"]["proposed_initial_active_size"], 1)
        self.assertEqual(document["counts"]["static_frontier_candidates_for_envelope_stage"], 1)
        self.assertFalse(document["verification"]["production_ready"])
        self.assertFalse(document["verification"]["perfect_play_claim"])
        self.assertEqual(document["work_avoidance"]["raw_directional_all_vs_all_matchups"], 4)
        self.assertEqual(document["work_avoidance"]["projected_initial_active_directional_matchups"], 1)


if __name__ == "__main__":
    unittest.main()
