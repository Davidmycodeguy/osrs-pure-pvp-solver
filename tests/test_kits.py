import unittest

from pure_solver.accounts import AccountState
from pure_solver.inventory import InventoryEntry, InventoryState
from pure_solver.kits import CombatKit, generate_combat_kits, inventory_fits_combat_kit
from pure_solver.legality import EquipmentItem, Loadout
from pure_solver.ruleset import load_ruleset


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


class CombatKitTests(unittest.TestCase):
    def test_verified_range_to_melee_kit_requires_compatible_ammo(self) -> None:
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        items = [EquipmentItem.from_document(item) for item in ruleset.items]
        account = AccountState(40, 40, 30, 1, 1, 40)
        search = generate_combat_kits(account, items)
        matching = [kit for kit in search.kits if (kit.primary_weapon.item_id == 853 and kit.ko_weapon.item_id == 1319)]
        self.assertGreater(len(matching), 1)
        self.assertTrue(all(kit.ammunition.item_id == 890 for kit in matching))
        kit = next(kit for kit in matching if kit.inventory_slots == 1)
        self.assertTrue(
            inventory_fits_combat_kit(
                InventoryState((InventoryEntry("swordfish", "whole", 26),), capacity=28),
                kit,
            )
        )
        self.assertTrue(
            inventory_fits_combat_kit(
                InventoryState((InventoryEntry("swordfish", "whole", 27),), capacity=28),
                kit,
            )
        )
        self.assertFalse(
            inventory_fits_combat_kit(
                InventoryState((InventoryEntry("swordfish", "whole", 28),), capacity=28),
                kit,
            )
        )

    def test_low_attack_account_cannot_generate_rune_ko_kit(self) -> None:
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        items = [EquipmentItem.from_document(item) for item in ruleset.items]
        account = AccountState(1, 40, 30, 1, 1, 40)
        search = generate_combat_kits(account, items)
        self.assertTrue(all(kit.ko_weapon.item_id not in {1319, 1333} for kit in search.kits))

    def test_combat_kit_tracks_common_worn_items_and_all_switch_slots(self) -> None:
        body = _item(item_id=10, slot="body", name="Body", bonuses={"attack_slash": 4, "melee_strength": 3})
        shield = _item(item_id=11, slot="shield", name="Shield", bonuses={"defence_slash": 8})
        bow = _item(
            item_id=12,
            slot="2h",
            name="Bow",
            two_handed=True,
            attack_speed=4,
            attack_styles=["accurate_ranged"],
            ammo_ids=[13],
        )
        arrows = _item(item_id=13, slot="ammo", name="Arrows", bonuses={"ranged_strength": 10})
        scimitar = _item(
            item_id=14,
            slot="weapon",
            name="Scimitar",
            attack_speed=4,
            attack_range=1,
            attack_styles=["accurate_slash"],
        )
        kit = CombatKit(
            primary_loadout=Loadout((body, bow, arrows)),
            ko_loadout=Loadout((body, scimitar, shield)),
        )
        self.assertEqual([item.item_id for item in kit.common_worn_items], [10])
        self.assertEqual(kit.inventory_slots, 2)
        self.assertEqual(kit.available_inventory_slots(28), 26)
        self.assertEqual(kit.equipped_bonuses("primary")["ranged_strength"], 10)
        self.assertEqual(kit.equipped_bonuses("ko")["attack_slash"], 4)
