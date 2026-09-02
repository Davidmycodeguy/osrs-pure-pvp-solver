import unittest

from pure_solver.accounts import AccountState
from pure_solver.errors import VerifiedMechanicMissingError
from pure_solver.inventory import InventoryEntry, InventoryState
from pure_solver.legality import EquipmentItem, Loadout, is_loadout_legal


def _item(**updates: object) -> EquipmentItem:
    raw: dict[str, object] = {
        "item_id": 1,
        "name": "test item",
        "free_to_play": True,
        "members": False,
        "obtainable": True,
        "slot": "weapon",
        "requirements": {},
        "bonuses": {},
        "source_ids": ["fixture"],
        "status": "verified",
        "availability_scope": "f2p_standard_world",
    }
    raw.update(updates)
    return EquipmentItem.from_document(raw)


class LegalityAndInventoryTests(unittest.TestCase):
    def test_inventory_enforces_28_slots_and_stackables_use_one(self) -> None:
        full = InventoryState((InventoryEntry("swordfish", "whole", quantity=28),), capacity=28)
        self.assertEqual(full.occupied_slots, 28)
        self.assertEqual(full.remaining_slots, 0)
        with self.assertRaises(ValueError):
            InventoryState((InventoryEntry("swordfish", "whole", quantity=29),), capacity=28)
        arrows = InventoryState(
            (InventoryEntry("adamant_arrow", "equipped", quantity=10_000, stackable=True),), capacity=28
        )
        self.assertEqual(arrows.occupied_slots, 1)

    def test_two_handed_loadout_rejects_shield(self) -> None:
        two_handed = _item(two_handed=True)
        shield = _item(item_id=2, slot="shield")
        self.assertFalse(is_loadout_legal(Loadout((two_handed, shield)), AccountState(1, 1, 1, 1, 1, 10)))

    def test_one_and_two_handed_weapons_cannot_be_equipped_together(self) -> None:
        one_handed = _item(item_id=1, slot="weapon")
        two_handed = _item(item_id=2, slot="2h", two_handed=True)
        self.assertFalse(is_loadout_legal(Loadout((one_handed, two_handed)), AccountState(1, 1, 1, 1, 1, 10)))

    def test_members_item_rejects_even_with_levels(self) -> None:
        members_item = _item(members=True)
        self.assertFalse(is_loadout_legal(Loadout((members_item,)), AccountState(99, 99, 99, 99, 99, 99)))

    def test_inventory_rejects_out_of_scope_consumables(self) -> None:
        inventory = InventoryState((InventoryEntry("anchovy_pizza", "full"),))
        with self.assertRaises(VerifiedMechanicMissingError):
            inventory.consume(
                "anchovy_pizza",
                {
                    "anchovy_pizza": {
                        "status": "verified",
                        "source_ids": ["fixture"],
                        "availability_scope": "lms",
                        "transitions": {"full": {"next_state": None, "healing": 9}},
                    },
                },
            )

    def test_pizza_bites_are_explicit_inventory_states(self) -> None:
        consumables = {
            "anchovy_pizza": {
                "status": "verified",
                "source_ids": ["fixture"],
                "availability_scope": "f2p_standard_world",
                "transitions": {
                    "full": {"next_state": "half", "healing": 9, "eat_delay_ticks": 1, "attack_delay_ticks": 3},
                    "half": {"next_state": None, "healing": 9, "eat_delay_ticks": 2, "attack_delay_ticks": 3},
                },
            },
        }
        inventory = InventoryState((InventoryEntry("anchovy_pizza", "full"),))
        after_first, first = inventory.consume("anchovy_pizza", consumables)
        after_second, second = after_first.consume("anchovy_pizza", consumables)
        self.assertEqual(after_first.entries, (InventoryEntry("anchovy_pizza", "half"),))
        self.assertEqual(after_second.entries, ())
        self.assertEqual(first["eat_delay_ticks"], 1)
        self.assertEqual(second["eat_delay_ticks"], 2)
