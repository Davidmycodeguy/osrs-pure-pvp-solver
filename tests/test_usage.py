import unittest

from pure_solver.errors import MechanicConflictError
from pure_solver.inventory import InventoryEntry, InventoryState
from pure_solver.ruleset import load_ruleset
from pure_solver.usage import measure_fight_usage, summarise_resource_usage


class ResourceUsageTests(unittest.TestCase):
    def setUp(self) -> None:
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        self.consumables = {item["consumable_id"]: item for item in ruleset.consumables}

    def test_full_pizza_counts_two_maximum_uses(self) -> None:
        initial = InventoryState(
            (
                InventoryEntry("anchovy_pizza", "full"),
                InventoryEntry("swordfish", "whole"),
            )
        )
        usage = measure_fight_usage(
            initial,
            InventoryState(()),
            ("anchovy_pizza", "anchovy_pizza", "swordfish"),
            self.consumables,
        )
        self.assertEqual(usage.maximum_actions_by_item, {"anchovy_pizza": 2, "swordfish": 1})
        self.assertEqual(usage.reached_maximum_by_item, {"anchovy_pizza": True, "swordfish": True})
        self.assertTrue(usage.all_food_consumed)

    def test_summary_reports_histogram_and_all_food_rate(self) -> None:
        initial = InventoryState(
            (
                InventoryEntry("anchovy_pizza", "full"),
                InventoryEntry("swordfish", "whole"),
            )
        )
        complete = measure_fight_usage(
            initial,
            InventoryState(()),
            ("anchovy_pizza", "anchovy_pizza", "swordfish"),
            self.consumables,
        )
        partial = measure_fight_usage(
            initial,
            InventoryState((InventoryEntry("anchovy_pizza", "half"), InventoryEntry("swordfish", "whole"))),
            ("anchovy_pizza",),
            self.consumables,
        )
        summary = summarise_resource_usage((complete, partial))
        self.assertEqual(summary.usage_histogram_by_item["anchovy_pizza"], {1: 1, 2: 1})
        self.assertEqual(summary.mean_actions_used_by_item["anchovy_pizza"], 1.5)
        self.assertEqual(summary.maximum_observed_actions_by_item["anchovy_pizza"], 2)
        self.assertEqual(summary.maximum_possible_actions_by_item["anchovy_pizza"], 2)
        self.assertEqual(summary.reached_maximum_rate_by_item["anchovy_pizza"], 0.5)
        self.assertEqual(summary.all_food_consumed_rate, 0.5)

    def test_different_starting_maxima_cannot_be_mixed(self) -> None:
        one = measure_fight_usage(
            InventoryState((InventoryEntry("anchovy_pizza", "full"),)),
            InventoryState(()),
            ("anchovy_pizza", "anchovy_pizza"),
            self.consumables,
        )
        two = measure_fight_usage(
            InventoryState((InventoryEntry("anchovy_pizza", "full", 2),)),
            InventoryState(()),
            ("anchovy_pizza",) * 4,
            self.consumables,
        )
        with self.assertRaises(MechanicConflictError):
            summarise_resource_usage((one, two))

    def test_four_dose_strength_potion_has_four_maximum_uses(self) -> None:
        initial = InventoryState((InventoryEntry("strength_potion", "4_dose"),))
        final = InventoryState((InventoryEntry("empty_vial", "empty"),))
        usage = measure_fight_usage(
            initial,
            final,
            ("strength_potion",) * 4,
            self.consumables,
        )
        self.assertEqual(usage.maximum_actions_by_item["strength_potion"], 4)
        self.assertTrue(usage.reached_maximum_by_item["strength_potion"])
        self.assertFalse(usage.has_food)
        self.assertFalse(usage.all_food_consumed)
        self.assertIsNone(summarise_resource_usage((usage,)).all_food_consumed_rate)
