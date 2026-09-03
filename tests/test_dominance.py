import unittest

from pure_solver.accounts import AccountState
from pure_solver.dominance import dominates_for_account, prune_dominated_items
from pure_solver.legality import EquipmentItem


def _weapon(
    item_id: int,
    name: str,
    attack_requirement: int,
    slash: int,
    strength: int,
    *,
    speed: int = 4,
    mechanic_flags: tuple[str, ...] = (),
) -> EquipmentItem:
    return EquipmentItem(
        item_id=item_id,
        name=name,
        free_to_play=True,
        members=False,
        obtainable=True,
        slot="weapon",
        requirements={"attack": attack_requirement},
        bonuses={"attack_slash": slash, "melee_strength": strength},
        weapon_type="scimitar",
        attack_speed=speed,
        attack_range=1,
        attack_styles=("accurate", "aggressive", "controlled", "defensive"),
        mechanic_flags=mechanic_flags,
        source_ids=("fixture",),
        status="verified",
        availability_scope="f2p_standard_world",
    )


class EquipmentDominanceTests(unittest.TestCase):
    def test_rune_scimitar_prunes_bronze_for_eligible_account(self) -> None:
        bronze = _weapon(1321, "Bronze scimitar", 1, 7, 5)
        rune = _weapon(1333, "Rune scimitar", 40, 45, 44)
        account = AccountState(40, 40, 1, 1, 1, 40)
        result = prune_dominated_items(account, [bronze, rune])
        self.assertEqual([item.name for item in result.retained], ["Rune scimitar"])
        self.assertEqual(result.pruned[0].dominated_item_id, bronze.item_id)
        self.assertEqual(result.pruned[0].dominating_item_id, rune.item_id)

    def test_rune_cannot_prune_bronze_when_rune_is_illegal(self) -> None:
        bronze = _weapon(1321, "Bronze scimitar", 1, 7, 5)
        rune = _weapon(1333, "Rune scimitar", 40, 45, 44)
        account = AccountState(1, 40, 1, 1, 1, 40)
        result = prune_dominated_items(account, [bronze, rune])
        self.assertEqual(result.retained, (bronze,))
        self.assertEqual(result.rejected_illegal, (rune,))

    def test_distinct_ko_or_special_mechanics_prevent_pruning(self) -> None:
        plain = _weapon(1, "Plain", 1, 10, 10)
        special = _weapon(2, "Special", 1, 9, 9, mechanic_flags=("delayed_hit",))
        account = AccountState(40, 40, 1, 1, 1, 40)
        self.assertFalse(dominates_for_account(plain, special, account))

    def test_slower_weapon_is_not_pruned_only_for_lower_dps(self) -> None:
        fast = _weapon(1, "Fast", 1, 20, 20, speed=4)
        slow_high_hit = _weapon(2, "Slow high hit", 1, 15, 30, speed=7)
        account = AccountState(40, 40, 1, 1, 1, 40)
        result = prune_dominated_items(account, [fast, slow_high_hit])
        self.assertEqual({item.item_id for item in result.retained}, {fast.item_id, slow_high_hit.item_id})

    def test_incompatible_ammunition_families_do_not_prune_each_other(self) -> None:
        def item(item_id: int, name: str, slot: str, ranged_strength: int, ammo_ids=()) -> EquipmentItem:
            return EquipmentItem(
                item_id=item_id,
                name=name,
                free_to_play=True,
                members=False,
                obtainable=True,
                slot=slot,
                requirements={},
                bonuses={"ranged_strength": ranged_strength},
                weapon_type="bow" if slot == "2h" else ("crossbow" if slot == "weapon" else None),
                attack_speed=4 if slot in {"weapon", "2h"} else None,
                attack_range=7 if slot in {"weapon", "2h"} else None,
                attack_styles=("rapid",) if slot in {"weapon", "2h"} else (),
                ammo_ids=tuple(ammo_ids),
                source_ids=("fixture",),
                status="verified",
                availability_scope="f2p_standard_world",
            )

        arrows = item(1, "Adamant arrows", "ammo", 31)
        bolts = item(2, "Bronze bolts", "ammo", 10)
        bow = item(3, "Maple shortbow", "2h", 0, ammo_ids=(1,))
        crossbow = item(4, "Crossbow", "weapon", 0, ammo_ids=(2,))
        result = prune_dominated_items(
            AccountState(40, 40, 40, 1, 1, 40),
            [arrows, bolts, bow, crossbow],
        )

        self.assertTrue({arrows.item_id, bolts.item_id}.issubset({entry.item_id for entry in result.retained}))
