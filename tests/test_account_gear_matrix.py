import tempfile
import unittest
from pathlib import Path

from pure_solver.account_gear_matrix import (
    KIT_MODES,
    _offence_bonus_names,
    _offence_pareto_items,
    build_account_gear_matrix,
    build_signature_gear,
)
from pure_solver.accounts import AccountState
from pure_solver.gear_matrix import write_verified_gear_matrix_csv
from pure_solver.legality import EquipmentItem
from pure_solver.ruleset import load_ruleset


def _item(item_id: int, name: str, slot: str, **bonuses: int) -> EquipmentItem:
    return EquipmentItem(
        item_id=item_id,
        name=name,
        free_to_play=True,
        members=False,
        obtainable=True,
        slot=slot,
        requirements={},
        bonuses=bonuses,
        status="verified",
        availability_scope="f2p",
    )


class AccountGearMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        cls.items = tuple(EquipmentItem.from_document(document) for document in cls.ruleset.items)

    def test_offence_bonus_names_follow_weapon_styles(self) -> None:
        scimitar = next(item for item in self.items if item.name == "Rune scimitar")
        # Scimitars carry slash styles plus a stab lunge; both accuracy axes matter.
        self.assertEqual(_offence_bonus_names(scimitar), ("attack_stab", "attack_slash", "melee_strength"))
        bow = next(item for item in self.items if item.name == "Maple shortbow")
        self.assertEqual(_offence_bonus_names(bow), ("attack_ranged", "ranged_strength"))

    def test_offence_pareto_keeps_strength_and_power_amulets_only(self) -> None:
        accuracy = _item(1, "Amulet of accuracy", "neck", attack_slash=4)
        strength = _item(2, "Amulet of strength", "neck", melee_strength=10)
        power = _item(3, "Amulet of power", "neck", attack_slash=6, melee_strength=6, defence_slash=6)
        magic = _item(4, "Amulet of magic", "neck", attack_magic=10)
        kept = _offence_pareto_items((accuracy, strength, power, magic), ("attack_slash", "melee_strength"))
        self.assertEqual({item.name for item in kept}, {"Amulet of strength", "Amulet of power"})

    def test_offence_pareto_tie_breaks_on_defence(self) -> None:
        weak = _item(1, "Iron full helm", "head", defence_slash=5)
        strong = _item(2, "Rune full helm", "head", defence_slash=30)
        self.assertEqual(_offence_pareto_items((weak, strong), ("attack_slash", "melee_strength")), (strong,))

    def test_offence_kit_is_much_smaller_than_full_kit(self) -> None:
        account = AccountState(40, 40, 40, 1, 1, 40)
        compact = build_signature_gear(account, self.items, kit_mode="offence_pareto")
        full = build_signature_gear(account, self.items, kit_mode="full")
        self.assertEqual(compact.weapon_options, full.weapon_options)
        self.assertLess(len(compact.row_items), len(full.row_items) / 10)
        for row in compact.row_items:
            slots = [item.slot for item in row]
            self.assertEqual(len(slots), len(set(slots)))

    def test_matrix_shares_gear_across_signature_and_writes_exact_levels(self) -> None:
        accounts = (
            AccountState(40, 40, 40, 1, 1, 40),
            AccountState(40, 40, 40, 5, 1, 41),  # same unlocks, different magic/hp
            AccountState(1, 1, 1, 1, 1, 10),
        )
        matrix, signatures = build_account_gear_matrix(accounts, self.items)
        self.assertEqual(signatures, 2)
        self.assertEqual(matrix.profile_count, 3)
        self.assertEqual(len(matrix.profiles[0].combinations), len(matrix.profiles[1].combinations))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matrix.csv"
            write_verified_gear_matrix_csv(matrix, path)
            header, first = path.read_text(encoding="utf-8").splitlines()[:2]
        columns = dict(zip(header.split(","), first.split(",")))
        self.assertEqual(columns["account_hitpoints"], "40")
        self.assertEqual(columns["attack_min"], columns["attack_max"])
        self.assertEqual(columns["account_defence"], "1")

    def test_unknown_kit_mode_rejected(self) -> None:
        self.assertNotIn("bogus", KIT_MODES)
        with self.assertRaises(ValueError):
            build_signature_gear(AccountState(1, 1, 1, 1, 1, 10), self.items, kit_mode="bogus")


if __name__ == "__main__":
    unittest.main()
