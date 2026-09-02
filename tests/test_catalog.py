import unittest

from pure_solver.accounts import AccountState
from pure_solver.catalog import EquipmentCatalog
from pure_solver.legality import EquipmentItem


def _observation(
    *,
    item_id: int,
    name: str,
    slot: str,
    requirements: dict[str, int],
    bonuses: dict[str, int],
    attack_speed: int | None = None,
    attack_range: int | None = None,
    combat_style: str | None = None,
    title: str | None = None,
) -> dict[str, object]:
    return {
        "source": {
            "title": title or name,
            "revision": f"r-{item_id}",
            "source_id": f"osrs-wiki:test:{item_id}",
            "url": f"https://example.test/{item_id}",
        },
        "observation": {
            "item_id": item_id,
            "name": name,
            "free_to_play": True,
            "members": False,
            "equipable": True,
            "slot": slot,
            "requirements": requirements,
            "bonuses": bonuses,
            "attack_speed": attack_speed,
            "attack_range": attack_range,
            "combat_style": combat_style,
            "source_ids": [f"osrs-wiki:test:{item_id}"],
            "status": "observed",
            "verification_gaps": ["obtainability", "skill_requirements", "quest_requirements"],
        },
    }


def _weapon_bonuses(slash: int, strength: int) -> dict[str, int]:
    return {
        "attack_stab": 0,
        "attack_slash": slash,
        "attack_crush": 0,
        "attack_magic": 0,
        "attack_ranged": 0,
        "defence_stab": 0,
        "defence_slash": 0,
        "defence_crush": 0,
        "defence_magic": 0,
        "defence_ranged": 0,
        "melee_strength": strength,
        "ranged_strength": 0,
        "magic_damage": 0,
        "prayer": 0,
    }


def _defensive_bonuses(defence: int) -> dict[str, int]:
    return {
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


class CatalogTests(unittest.TestCase):
    def test_catalog_groups_equivalents_and_flags_lineage_conflicts(self) -> None:
        snapshot = {
            "observation_snapshot_id": "snapshot-1",
            "query": "is:f2p",
            "observations": [
                _observation(
                    item_id=1,
                    name="Bronze sword",
                    slot="weapon",
                    requirements={},
                    bonuses=_weapon_bonuses(4, 3),
                    attack_speed=4,
                    attack_range=1,
                    combat_style="Slash Sword",
                ),
                _observation(
                    item_id=2,
                    name="Bronze sword (ornament)",
                    slot="weapon",
                    requirements={},
                    bonuses=_weapon_bonuses(4, 3),
                    attack_speed=4,
                    attack_range=1,
                    combat_style="Slash Sword",
                ),
                _observation(
                    item_id=3,
                    name="Rune scimitar",
                    slot="weapon",
                    requirements={"attack": 40},
                    bonuses=_weapon_bonuses(45, 44),
                    attack_speed=4,
                    attack_range=1,
                    combat_style="Slash Sword",
                ),
                _observation(
                    item_id=4,
                    name="Rune scimitar (guthix)",
                    slot="weapon",
                    requirements={},
                    bonuses=_weapon_bonuses(45, 44),
                    attack_speed=4,
                    attack_range=1,
                    combat_style="Slash Sword",
                ),
                _observation(
                    item_id=5,
                    name="Iron full helm",
                    slot="head",
                    requirements={},
                    bonuses=_defensive_bonuses(5),
                ),
                _observation(
                    item_id=6,
                    name="Amulet of power (Last Man Standing)",
                    slot="neck",
                    requirements={},
                    bonuses={
                        "attack_stab": 6,
                        "attack_slash": 6,
                        "attack_crush": 6,
                        "attack_magic": 6,
                        "attack_ranged": 6,
                        "defence_stab": 6,
                        "defence_slash": 6,
                        "defence_crush": 6,
                        "defence_magic": 6,
                        "defence_ranged": 6,
                        "melee_strength": 6,
                        "ranged_strength": 0,
                        "magic_damage": 0,
                        "prayer": 1,
                    },
                ),
            ],
            "failures": [
                {
                    "title": "Magic staff",
                    "revision": "15234369",
                    "error": "DataUnavailableError: Equipment field 'attackrange' is not an exact integer: 'staff'",
                }
            ],
        }
        verified_items = [
            EquipmentItem.from_document(
                {
                    "item_id": 100,
                    "name": "Amulet of power",
                    "free_to_play": True,
                    "members": False,
                    "obtainable": True,
                    "slot": "neck",
                    "requirements": {},
                    "quest_requirements": [],
                    "bonuses": {
                        "attack_stab": 6,
                        "attack_slash": 6,
                        "attack_crush": 6,
                        "attack_magic": 6,
                        "attack_ranged": 6,
                        "defence_stab": 6,
                        "defence_slash": 6,
                        "defence_crush": 6,
                        "defence_magic": 6,
                        "defence_ranged": 6,
                        "melee_strength": 6,
                        "ranged_strength": 0,
                        "magic_damage": 0,
                        "prayer": 1,
                    },
                    "attack_speed": None,
                    "attack_range": None,
                    "attack_styles": [],
                    "ammo_ids": [],
                    "spell_ids": [],
                    "mechanic_flags": [],
                    "source_ids": ["osrs-wiki:test:100"],
                    "status": "verified",
                    "availability_scope": "f2p_standard_world",
                }
            ),
        ]
        catalog = EquipmentCatalog.from_documents(snapshot, verified_items=verified_items)

        summary = catalog.summary()
        self.assertEqual(summary.observation_count, 6)
        self.assertEqual(summary.failure_count, 1)
        self.assertEqual(summary.verified_item_count, 1)
        self.assertEqual(summary.pending_item_count, 6)
        self.assertEqual(summary.promotion_group_count, 4)
        self.assertEqual(summary.lineage_conflict_count, 1)
        self.assertEqual(summary.covered_pending_group_count, 0)

        duplicates = catalog.duplicate_groups()
        self.assertTrue(any(group.kind == "exact_signature" and group.item_ids == (1, 2) for group in duplicates))
        self.assertTrue(any(group.kind == "lineage" and group.item_ids == (3, 4) for group in duplicates))

        validation = catalog.validation_queue()
        self.assertEqual(validation[0].code, "parser_failure")
        self.assertTrue(any(issue.code == "verified_item_missing_from_snapshot" for issue in validation))
        self.assertTrue(any(issue.code == "lineage_conflict" and issue.item_ids == (3, 4) for issue in validation))
        self.assertTrue(
            any(issue.code == "environment_scoped_variant" and issue.item_ids == (6,) for issue in validation)
        )

        queue = catalog.promotion_queue(AccountState(1, 1, 1, 1, 1, 10))
        self.assertEqual(queue[0].representative_item_id, 1)
        self.assertIn("collapsed_equivalents:2", queue[0].tags)
        self.assertTrue(queue[0].account_legal_by_observation)
        rune_group = next(candidate for candidate in queue if candidate.representative_item_id == 3)
        self.assertFalse(rune_group.account_legal_by_observation)
        self.assertFalse(any(candidate.representative_item_id == 6 for candidate in queue))

        relevant = catalog.relevant_subset(AccountState(1, 1, 1, 1, 1, 10))
        self.assertEqual(relevant.legal_verified_item_ids, (100,))
        self.assertEqual(relevant.covered_group_count, 0)
        self.assertEqual(relevant.blocked_group_count, 1)

    def test_real_snapshot_smoke_test(self) -> None:
        catalog = EquipmentCatalog.from_paths(
            "research/observations/f2p-equipment.json",
            verified_items_path="rulesets/osrs-f2p-v1/items.json",
        )
        summary = catalog.summary()
        self.assertEqual(summary.observation_count, 1091)
        self.assertEqual(summary.failure_count, 25)
        self.assertEqual(summary.verified_item_count, 150)
        self.assertEqual(summary.pending_item_count, 945)
        self.assertLess(summary.promotion_group_count, summary.pending_item_count)
        self.assertGreater(summary.lineage_conflict_count, 0)
        self.assertIn("weapon", summary.by_slot)

        validation = catalog.validation_queue()
        self.assertTrue(any(issue.code == "parser_failure" for issue in validation))
        self.assertTrue(any(issue.code == "lineage_conflict" and 1333 in issue.item_ids for issue in validation))

        account = AccountState(40, 40, 30, 1, 1, 40)
        relevant = catalog.relevant_subset(account)
        self.assertTrue(
            {851, 853, 890, 1289, 1319, 1333, 1347, 1373, 1432, 12727, 20756, 23360, 24219, 25641}.issubset(
                set(relevant.legal_verified_item_ids)
            )
        )
        self.assertGreater(relevant.uncovered_group_count, 0)
