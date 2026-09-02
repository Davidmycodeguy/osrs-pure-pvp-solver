import tempfile
import unittest
from pathlib import Path

from pure_solver.account_frontier import (
    account_levels,
    enumerate_exact_combat_accounts,
    equipment_unlock_signature,
    maximum_magic_for_combat,
    pareto_frontier,
    prayer_level_choices,
    read_account_frontier_csv,
    top_ranked_accounts,
    write_account_frontier_csv,
)
from pure_solver.accounts import AccountState
from pure_solver.experience import standard_f2p_hitpoints_achievable
from pure_solver.legality import EquipmentItem
from pure_solver.ruleset import load_ruleset


class AccountFrontierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        cls.mechanics = cls.ruleset.mechanics

    def test_placeholder_hp_account_is_not_a_combat_30_candidate(self) -> None:
        # Attack 30 / Strength 20 / Ranged 30 cannot reach combat 30 at any reachable HP (28-29);
        # a placeholder 10 HP does not change that.
        for hitpoints in (10, 28, 29):
            account = AccountState(30, 20, 30, 1, 1, hitpoints)
            self.assertLess(account.combat_level(self.mechanics), 30)
        # Only Magic can lift it to 30; the frontier fills exactly that much and no more.
        magic = maximum_magic_for_combat(
            attack=30,
            strength=20,
            ranged=30,
            prayer=1,
            hitpoints=28,
            combat_level=30,
        )
        self.assertEqual(magic, 49)
        self.assertEqual(AccountState(30, 20, 30, 49, 1, 28).combat_level(self.mechanics), 30)
        self.assertEqual(AccountState(30, 20, 30, 50, 1, 28).combat_level(self.mechanics), 31)

    def test_prayer_choices_lift_even_breakpoints_to_free_odd_level(self) -> None:
        choices = prayer_level_choices(self.mechanics)
        self.assertIn(1, choices)
        self.assertTrue(all(level % 2 == 1 for level in choices))
        self.assertNotIn(4, choices)
        self.assertIn(5, choices)

    def test_maximum_magic_keeps_combat_level_exact(self) -> None:
        magic = maximum_magic_for_combat(
            attack=35,
            strength=35,
            ranged=9,
            prayer=1,
            hitpoints=31,
            combat_level=30,
        )
        self.assertEqual(magic, 47)
        self.assertEqual(AccountState(35, 35, 9, 47, 1, 31).combat_level(self.mechanics), 30)
        self.assertEqual(AccountState(35, 35, 9, 48, 1, 31).combat_level(self.mechanics), 31)

    def test_enumerated_accounts_are_exact_and_reachable(self) -> None:
        sample = []
        for account in enumerate_exact_combat_accounts(
            self.mechanics,
            combat_level=30,
            prayer_levels=(1, 13),
        ):
            sample.append(account)
            if len(sample) == 2_000:
                break
        self.assertTrue(sample)
        for account in sample:
            self.assertEqual(account.defence_level, 1)
            self.assertEqual(account.combat_level(self.mechanics), 30)
            self.assertTrue(standard_f2p_hitpoints_achievable(account, self.mechanics))
            self.assertIn(account.prayer_level, (1, 13))

    def test_pareto_frontier_drops_dominated_accounts(self) -> None:
        weaker = AccountState(30, 30, 1, 40, 1, 30)
        stronger_hp = AccountState(30, 30, 1, 40, 1, 31)
        stronger_prayer = AccountState(30, 30, 1, 40, 5, 30)
        more_magic = AccountState(30, 30, 1, 42, 1, 30)
        accounts = (weaker, stronger_hp, stronger_prayer, more_magic)
        with_magic = pareto_frontier(accounts, ignore_magic=False)
        self.assertNotIn(weaker, with_magic)
        self.assertIn(more_magic, with_magic)
        without_magic = pareto_frontier(accounts, ignore_magic=True)
        self.assertNotIn(weaker, without_magic)
        self.assertNotIn(more_magic, without_magic)
        self.assertEqual(set(without_magic), {stronger_hp, stronger_prayer})

    def test_top_ranked_accounts_are_distinct_and_rank_ordered(self) -> None:
        header = "rank,account_attack,account_strength,account_ranged,account_magic,account_prayer,account_hitpoints\n"
        rows = ("3,30,30,1,40,1,31\n", "1,35,35,9,47,1,31\n", "2,35,35,9,47,1,31\n", "4,20,40,1,40,1,31\n")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ranked.csv"
            path.write_text(header + "".join(rows), encoding="utf-8")
            top = top_ranked_accounts(path, limit=2)
        self.assertEqual([account_levels(a) for a in top], [(35, 35, 9, 47, 1, 31), (30, 30, 1, 40, 1, 31)])

    def test_unlock_signature_and_csv_round_trip(self) -> None:
        items = tuple(EquipmentItem.from_document(document) for document in self.ruleset.items)
        low = AccountState(1, 1, 1, 1, 1, 10)
        high = AccountState(40, 40, 40, 1, 1, 40)
        self.assertLess(equipment_unlock_signature(low, items), equipment_unlock_signature(high, items))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frontier.csv"
            write_account_frontier_csv((low, high), self.mechanics, path)
            restored = read_account_frontier_csv(path)
        self.assertEqual([account_levels(a) for a in restored], [account_levels(low), account_levels(high)])


if __name__ == "__main__":
    unittest.main()
