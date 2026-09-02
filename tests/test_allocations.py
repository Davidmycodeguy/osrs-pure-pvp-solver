import unittest

from pure_solver.accounts import AccountState
from pure_solver.allocations import InventoryOption, generate_inventory_allocations
from pure_solver.kits import generate_combat_kits
from pure_solver.legality import EquipmentItem
from pure_solver.ruleset import load_ruleset


class InventoryAllocationTests(unittest.TestCase):
    def test_switch_slots_reduce_consumable_capacity(self) -> None:
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        items = [EquipmentItem.from_document(item) for item in ruleset.items]
        search = generate_combat_kits(AccountState(40, 40, 30, 1, 1, 40), items)
        kit = next(
            kit
            for kit in search.kits
            if (kit.primary_weapon.item_id == 853 and kit.ko_weapon.item_id == 1319 and kit.inventory_slots == 1)
        )
        allocations = generate_inventory_allocations(
            kit,
            (
                InventoryOption("anchovy_pizza", "full", maximum_count=28),
                InventoryOption("swordfish", "whole", maximum_count=28),
                InventoryOption("strength_potion", "4_dose", maximum_count=2),
            ),
            capacity=ruleset.inventory_slots,
            fill_capacity=True,
        )
        self.assertGreater(len(allocations), 0)
        self.assertTrue(all(allocation.total_slots_used == 28 for allocation in allocations))
        self.assertTrue(all(allocation.inventory.occupied_slots == 27 for allocation in allocations))
        self.assertEqual(len({allocation.canonical_id for allocation in allocations}), len(allocations))
