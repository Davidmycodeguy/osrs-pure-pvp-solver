import csv
import json
import tempfile
import unittest
from pathlib import Path

from pure_solver.accounts import AccountState
from pure_solver.catalog import EquipmentCatalog
from pure_solver.gear_catalog_export import (
    build_account_gear_export,
    observed_account_representatives,
    verified_level_item_profiles,
    write_account_gear_json,
    write_observed_representatives_csv,
    write_verified_survivors_csv,
)
from pure_solver.legality import EquipmentItem


def _entry(
    item_id: int,
    name: str,
    *,
    members: bool = False,
    requirements: dict[str, int] | None = None,
    defence: int = 1,
) -> dict[str, object]:
    bonuses = {
        "attack_stab": 0,
        "attack_slash": 0,
        "attack_crush": 0,
        "attack_magic": 0,
        "attack_ranged": 0,
        "defence_stab": defence,
        "defence_slash": defence,
        "defence_crush": defence,
        "defence_magic": 0,
        "defence_ranged": defence,
        "melee_strength": 0,
        "ranged_strength": 0,
        "magic_damage": 0,
        "prayer": 0,
    }
    return {
        "source": {
            "title": name,
            "revision": str(item_id),
            "source_id": f"wiki:{item_id}",
            "url": f"https://example.test/{item_id}",
        },
        "observation": {
            "item_id": item_id,
            "name": name,
            "free_to_play": not members,
            "members": members,
            "equipable": True,
            "slot": "shield",
            "requirements": requirements or {},
            "bonuses": bonuses,
            "attack_speed": None,
            "attack_range": None,
            "combat_style": None,
            "source_ids": [f"wiki:{item_id}"],
            "status": "observed",
            "verification_gaps": ["quest_requirements"],
        },
    }


def _verified(item_id: int, name: str) -> EquipmentItem:
    document = _entry(item_id, name)["observation"]
    return EquipmentItem.from_document(
        {
            **document,
            "free_to_play": True,
            "members": False,
            "obtainable": True,
            "quest_requirements": [],
            "two_handed": False,
            "weapon_type": None,
            "attack_styles": [],
            "ammo_ids": [],
            "spell_ids": [],
            "mechanic_flags": [],
            "status": "verified",
            "availability_scope": "f2p_standard_world",
        }
    )


class GearCatalogExportTests(unittest.TestCase):
    def test_level_profiles_preserve_lower_tier_items_until_the_upgrade_is_legal(self) -> None:
        bronze = EquipmentItem.from_document(
            {
                **_entry(100, "Bronze sword")["observation"],
                "free_to_play": True,
                "members": False,
                "obtainable": True,
                "requirements": {},
                "quest_requirements": [],
                "two_handed": False,
                "weapon_type": "sword",
                "attack_speed": 4,
                "attack_range": 1,
                "attack_styles": ["accurate_stab"],
                "ammo_ids": [],
                "spell_ids": [],
                "mechanic_flags": [],
                "bonuses": {"attack_stab": 4, "melee_strength": 3},
                "source_ids": ["fixture"],
                "status": "verified",
                "availability_scope": "f2p_standard_world",
            }
        )
        rune = EquipmentItem.from_document(
            {
                **_entry(101, "Rune sword")["observation"],
                "free_to_play": True,
                "members": False,
                "obtainable": True,
                "requirements": {"attack": 40},
                "quest_requirements": [],
                "two_handed": False,
                "weapon_type": "sword",
                "attack_speed": 4,
                "attack_range": 1,
                "attack_styles": ["accurate_stab"],
                "ammo_ids": [],
                "spell_ids": [],
                "mechanic_flags": [],
                "bonuses": {"attack_stab": 38, "melee_strength": 39},
                "source_ids": ["fixture"],
                "status": "verified",
                "availability_scope": "f2p_standard_world",
            }
        )

        profiles = verified_level_item_profiles([bronze, rune], maximum_level=40)

        self.assertEqual(len(profiles), 2)
        self.assertEqual(profiles[0].level_minimums["attack"], 1)
        self.assertEqual(profiles[0].level_maximums["attack"], 39)
        self.assertEqual([item.name for item in profiles[0].retained_items], ["Bronze sword"])
        self.assertEqual([item.name for item in profiles[1].retained_items], ["Rune sword"])

    def test_filters_before_collapsing_and_prefers_verified_plain_variant(self) -> None:
        snapshot = {
            "query": "f2p",
            "observation_snapshot_id": "snapshot",
            "observations": [
                _entry(10, "Iron kiteshield (g)"),
                _entry(1, "Iron kiteshield"),
                _entry(11, "Members shield", members=True),
                _entry(12, "Adamant kiteshield", requirements={"defence": 30}, defence=30),
                _entry(13, "Wooden shield", defence=0),
            ],
            "failures": [],
        }
        catalog = EquipmentCatalog.from_documents(snapshot, verified_items=[_verified(1, "Iron kiteshield")])
        account = AccountState(40, 40, 40, 40, 40, 40)

        rows = observed_account_representatives(catalog, account)
        self.assertEqual([row.representative_item_id for row in rows], [1, 13])
        iron = next(row for row in rows if row.representative_item_id == 1)
        self.assertEqual(iron.exact_variant_item_ids, (1, 10))
        self.assertEqual(iron.covered_by_verified_item_ids, (1,))

        payload = build_account_gear_export(catalog, account)
        self.assertEqual(payload["counts"]["account_legal_observed_items_before_exact_collapse"], 3)
        self.assertEqual(payload["counts"]["observed_exact_variants_collapsed"], 1)

    def test_writers_preserve_auditable_variant_columns(self) -> None:
        catalog = EquipmentCatalog.from_documents(
            {
                "observations": [_entry(1, "Iron kiteshield"), _entry(2, "Iron kiteshield (g)")],
                "failures": [],
            },
            verified_items=[_verified(1, "Iron kiteshield")],
        )
        payload = build_account_gear_export(catalog, AccountState(40, 40, 40, 40, 40, 40))
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "gear.json"
            csv_path = Path(directory) / "gear.csv"
            survivor_path = Path(directory) / "survivors.csv"
            write_account_gear_json(payload, json_path)
            write_observed_representatives_csv(payload["observed_exact_representatives"], csv_path)
            write_verified_survivors_csv(payload["verified_dominance_survivors"], survivor_path)
            decoded = json.loads(json_path.read_text(encoding="utf-8"))
            rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
            survivor_rows = list(csv.DictReader(survivor_path.open(encoding="utf-8")))

        self.assertEqual(decoded["method"]["observed_pruning"], "exact observed signature equivalence only")
        self.assertEqual(rows[0]["exact_variant_item_ids"], "1;2")
        self.assertEqual(rows[0]["exact_variant_count"], "2")
        self.assertIn("req_prayer", rows[0])
        self.assertIn("prayer", rows[0])
        self.assertEqual(survivor_rows[0]["name"], "Iron kiteshield")
        self.assertEqual(survivor_rows[0]["req_defence"], "0")

    def test_real_snapshot_is_f2p_one_defence_and_collapses_adamant_variants_only_when_legal(self) -> None:
        catalog = EquipmentCatalog.from_paths(
            "research/observations/f2p-equipment.json",
            verified_items_path="rulesets/osrs-f2p-v1/items.json",
        )
        rows = observed_account_representatives(catalog, AccountState(40, 40, 40, 40, 40, 40))
        all_ids = {item_id for row in rows for item_id in row.exact_variant_item_ids}
        names = {row.representative_name for row in rows}

        self.assertIn(1191, all_ids)
        self.assertIn("Iron kiteshield", names)
        self.assertNotIn(1123, all_ids)
        self.assertNotIn(2607, all_ids)
        self.assertTrue(all(row.requirements.get("defence", 0) <= 1 for row in rows))


if __name__ == "__main__":
    unittest.main()
