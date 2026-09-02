import json
import unittest
from pathlib import Path

from pure_solver.consumable_dominance import prune_dominated_foods
from pure_solver.ruleset import load_ruleset
from pure_solver.wiki_consumables import observe_consumable


class ConsumableDominanceTests(unittest.TestCase):
    def test_lobster_is_verified_then_strictly_pruned_by_swordfish(self) -> None:
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        result = prune_dominated_foods(ruleset.consumables)
        self.assertEqual(
            {option.consumable_id for option in result.retained},
            {"anchovy_pizza", "swordfish"},
        )
        self.assertEqual(
            {(record.dominated_consumable_id, record.dominating_consumable_id) for record in result.pruned},
            {
                ("easter_egg", "swordfish"),
                ("lobster", "swordfish"),
                ("meat_pizza", "anchovy_pizza"),
                ("pumpkin", "swordfish"),
                ("tuna", "swordfish"),
            },
        )
        pruned = {record.dominated_consumable_id: record.dominating_consumable_id for record in result.pruned}
        self.assertEqual(pruned["tuna"], "swordfish")
        self.assertEqual(pruned["meat_pizza"], "anchovy_pizza")
        self.assertEqual(pruned["pumpkin"], "swordfish")
        self.assertEqual(pruned["easter_egg"], "swordfish")

    def test_shark_is_source_observed_as_members_only_and_never_promoted(self) -> None:
        source = json.loads(Path("research/authoritative/shark.json").read_text(encoding="utf-8"))
        observation = observe_consumable(source)
        self.assertFalse(observation.free_to_play)
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        self.assertNotIn("shark", {item["consumable_id"] for item in ruleset.consumables})
