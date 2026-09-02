import unittest
from pathlib import Path

from pure_solver.catalog_scope import audit_catalog_scope, load_catalog_scope
from pure_solver.errors import DataUnavailableError


class CatalogScopeTests(unittest.TestCase):
    def test_loads_explicitly_classified_catalog(self) -> None:
        audit = audit_catalog_scope(
            {
                "scope": "fixture",
                "catalog_complete": False,
                "candidate_ids": ["rune_scimitar", "bronze_sword", "jug_of_wine", "lms_amulet", "meat_pizza"],
                "promoted": [{"item_id": "rune_scimitar"}],
                "dominance_pruned": [{"item_id": "bronze_sword"}],
                "mechanics_blocked": [{"item_id": "jug_of_wine"}],
                "environment_excluded": [{"item_id": "lms_amulet"}],
                "pending": [{"item_id": "meat_pizza"}],
            }
        )

        self.assertEqual(audit.scope, "fixture")
        self.assertEqual(
            audit.candidate_ids, ("rune_scimitar", "bronze_sword", "jug_of_wine", "lms_amulet", "meat_pizza")
        )
        self.assertEqual(audit.promoted, ("rune_scimitar",))
        self.assertEqual(audit.dominance_pruned, ("bronze_sword",))
        self.assertEqual(audit.mechanics_blocked, ("jug_of_wine",))
        self.assertEqual(audit.environment_excluded, ("lms_amulet",))
        self.assertEqual(audit.pending, ("meat_pizza",))
        self.assertFalse(audit.production_catalog_complete)
        self.assertFalse(audit.exhaustive_claim_safe)
        self.assertEqual(audit.counts["candidate_count"], 5)

    def test_legacy_food_scope_aliases_load_from_path(self) -> None:
        audit = load_catalog_scope(Path("rulesets/osrs-f2p-v1/food-scope.json"))

        self.assertEqual(audit.scope, "f2p_standard_world_pvp")
        self.assertEqual(audit.promoted, ("anchovy_pizza", "swordfish"))
        self.assertEqual(
            audit.dominance_pruned,
            ("easter_egg", "lobster", "meat_pizza", "pumpkin", "tuna"),
        )
        self.assertEqual(audit.mechanics_blocked, ("jug_of_wine", "kebab"))
        self.assertEqual(audit.environment_excluded, ("shark",))
        self.assertEqual(audit.pending, ())
        self.assertFalse(audit.declared_catalog_complete)
        self.assertFalse(audit.production_catalog_complete)

    def test_rejects_duplicate_classification(self) -> None:
        with self.assertRaisesRegex(DataUnavailableError, "classified more than once"):
            audit_catalog_scope(
                {
                    "scope": "fixture",
                    "promoted": [{"item_id": "rune_scimitar"}],
                    "pending": [{"item_id": "rune_scimitar"}],
                }
            )

    def test_rejects_declared_candidates_without_status(self) -> None:
        with self.assertRaisesRegex(DataUnavailableError, "missing a status classification"):
            audit_catalog_scope(
                {
                    "scope": "fixture",
                    "candidate_ids": ["rune_scimitar", "jug_of_wine"],
                    "promoted": [{"item_id": "rune_scimitar"}],
                }
            )

    def test_rejects_catalog_complete_when_pending_exists(self) -> None:
        with self.assertRaisesRegex(DataUnavailableError, "pending candidates remain"):
            audit_catalog_scope(
                {
                    "scope": "fixture",
                    "catalog_complete": True,
                    "promoted": [{"item_id": "rune_scimitar"}],
                    "pending": [{"item_id": "meat_pizza"}],
                }
            )

    def test_rejects_catalog_complete_when_mechanics_blocked_exists(self) -> None:
        with self.assertRaisesRegex(DataUnavailableError, "prevent an exhaustive claim"):
            audit_catalog_scope(
                {
                    "scope": "fixture",
                    "catalog_complete": True,
                    "promoted": [{"item_id": "rune_scimitar"}],
                    "mechanics_blocked": [{"item_id": "jug_of_wine"}],
                }
            )

    def test_accepts_complete_catalog_only_when_no_pending_or_blocked_entries_remain(self) -> None:
        audit = audit_catalog_scope(
            {
                "scope": "fixture",
                "catalog_complete": True,
                "candidate_ids": ["rune_scimitar", "bronze_sword"],
                "promoted": [{"item_id": "rune_scimitar"}],
                "dominance_pruned": [{"item_id": "bronze_sword"}],
            }
        )

        self.assertTrue(audit.declared_catalog_complete)
        self.assertTrue(audit.production_catalog_complete)
        self.assertTrue(audit.exhaustive_claim_safe)

    def test_rejects_ambiguous_identifier_entries(self) -> None:
        with self.assertRaisesRegex(DataUnavailableError, "ambiguous id fields"):
            audit_catalog_scope(
                {
                    "scope": "fixture",
                    "promoted": [{"item_id": "rune_scimitar", "consumable_id": "swordfish"}],
                }
            )


if __name__ == "__main__":
    unittest.main()
