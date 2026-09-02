import json
import unittest
from pathlib import Path

from pure_solver.consumable_verification import build_verified_consumable_documents
from pure_solver.errors import DataUnavailableError
from pure_solver.inventory import InventoryEntry, InventoryState
from pure_solver.potion_verification import build_verified_potion_documents
from pure_solver.ruleset import load_ruleset


class ConsumableVerificationTests(unittest.TestCase):
    def test_committed_snapshot_regenerates_and_applies_real_transitions(self) -> None:
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        decisions = json.loads(Path("rulesets/osrs-f2p-v1/consumable-verification.json").read_text(encoding="utf-8"))
        regenerated = build_verified_consumable_documents(
            ruleset.source_archive, decisions, set(ruleset.mechanics.source_revisions)
        )
        regenerated.extend(
            build_verified_potion_documents(ruleset.source_archive, decisions, set(ruleset.mechanics.source_revisions))
        )
        regenerated.sort(key=lambda item: item["consumable_id"])
        committed = json.loads(Path("rulesets/osrs-f2p-v1/consumables.json").read_text(encoding="utf-8"))
        self.assertEqual(regenerated, committed)
        definitions = {item["consumable_id"]: item for item in committed}
        inventory = InventoryState((InventoryEntry("anchovy_pizza", "full"),))
        after_first, first = inventory.consume("anchovy_pizza", definitions)
        after_second, second = after_first.consume("anchovy_pizza", definitions)
        self.assertEqual(first["healing"], 9)
        self.assertEqual(first["eat_delay_ticks"], 1)
        self.assertEqual(second["eat_delay_ticks"], 2)
        self.assertEqual(after_second.entries, ())

    def test_strength_potion_dose_states_regenerate_from_source(self) -> None:
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        definitions = {item["consumable_id"]: item for item in ruleset.consumables}
        inventory = InventoryState((InventoryEntry("strength_potion", "4_dose"),))
        states = []
        for _ in range(4):
            inventory, transition = inventory.consume("strength_potion", definitions)
            states.append((inventory.entries[0].item_id, inventory.entries[0].state))
            self.assertEqual(transition["drink_delay_ticks"], 3)
            self.assertEqual(transition["attack_delay_ticks"], 0)
        self.assertEqual(
            states,
            [
                ("strength_potion", "3_dose"),
                ("strength_potion", "2_dose"),
                ("strength_potion", "1_dose"),
                ("empty_vial", "empty"),
            ],
        )

    def test_wrong_identity_and_nonterminating_food_are_rejected(self) -> None:
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        decisions = json.loads(Path("rulesets/osrs-f2p-v1/consumable-verification.json").read_text(encoding="utf-8"))
        wrong_identity = json.loads(json.dumps(decisions))
        wrong_identity["consumables"][0]["consumable_id"] = "anchovy_pizza"
        with self.assertRaises(DataUnavailableError):
            build_verified_consumable_documents(
                ruleset.source_archive, wrong_identity, set(ruleset.mechanics.source_revisions)
            )
        loop = json.loads(json.dumps(decisions))
        loop["consumables"][1]["transitions"]["full"]["next_state"] = "full"
        with self.assertRaises(DataUnavailableError):
            build_verified_consumable_documents(ruleset.source_archive, loop, set(ruleset.mechanics.source_revisions))

    def test_consumable_without_standard_world_scope_cannot_be_promoted(self) -> None:
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        decisions = json.loads(Path("rulesets/osrs-f2p-v1/consumable-verification.json").read_text(encoding="utf-8"))
        decisions["consumables"][0]["availability_scope"] = "members"
        with self.assertRaisesRegex(DataUnavailableError, "standard-world scope"):
            build_verified_consumable_documents(
                ruleset.source_archive, decisions, set(ruleset.mechanics.source_revisions)
            )
