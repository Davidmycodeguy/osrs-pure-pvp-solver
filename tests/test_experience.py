import unittest
from fractions import Fraction

from pure_solver.accounts import AccountSearchBounds, AccountState, LevelRange, enumerate_account_states
from pure_solver.errors import LegalityError
from pure_solver.experience import (
    AchievabilityRules,
    HistoricalAccountProof,
    TrainingEvent,
    combat_level_hitpoints_interval,
    enumerate_standard_f2p_account_states,
    level_for_xp,
    minimum_standard_f2p_hitpoints_level,
    standard_f2p_hitpoints_achievable,
    standard_f2p_hitpoints_levels,
    xp_for_level,
)
from pure_solver.ruleset import load_ruleset


class ExperienceAndAchievabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mechanics = load_ruleset("rulesets/osrs-f2p-v1").mechanics

    def test_xp_level_golden_thresholds(self) -> None:
        self.assertEqual(xp_for_level(1, self.mechanics), 0)
        self.assertEqual(xp_for_level(2, self.mechanics), 83)
        self.assertEqual(xp_for_level(40, self.mechanics), 37_224)
        self.assertEqual(xp_for_level(99, self.mechanics), 13_034_431)
        self.assertEqual(level_for_xp(37_223, self.mechanics), 39)
        self.assertEqual(level_for_xp(37_224, self.mechanics), 40)

    def test_training_history_proves_exact_account_and_restrictions(self) -> None:
        initial = {
            skill: Fraction(0) for skill in ("attack", "strength", "ranged", "magic", "prayer", "hitpoints", "defence")
        }
        initial["hitpoints"] = Fraction(xp_for_level(10, self.mechanics))
        event = TrainingEvent(
            "fixture-training",
            1,
            {"attack": Fraction(83)},
            frozenset({"members_training"}),
            ("osrs-wiki:2086:15167522",),
            "verified",
        )
        proof = HistoricalAccountProof(initial, (event,))
        self.assertTrue(proof.proves(AccountState(2, 1, 1, 1, 1, 10), self.mechanics))
        with self.assertRaises(LegalityError):
            proof.final_xp(self.mechanics, AchievabilityRules(frozenset({"members_training"})))

    def test_standard_f2p_training_rejects_impossible_low_hp(self) -> None:
        low = AccountState(40, 60, 1, 1, 34, 10)
        self.assertEqual(minimum_standard_f2p_hitpoints_level(low, self.mechanics), 50)
        self.assertFalse(standard_f2p_hitpoints_achievable(low, self.mechanics))
        self.assertTrue(standard_f2p_hitpoints_achievable(AccountState(40, 60, 1, 1, 34, 50), self.mechanics))

    def test_direct_hp_intersection_for_ranged_combat_thirty(self) -> None:
        probe = AccountState(1, 1, 44, 1, 8, 33)
        self.assertEqual(
            combat_level_hitpoints_interval(probe, self.mechanics, combat_minimum=30, combat_maximum=30),
            (30, 33),
        )
        self.assertEqual(
            standard_f2p_hitpoints_levels(
                attack_level=1,
                strength_level=1,
                ranged_level=44,
                mechanics=self.mechanics,
                requested=LevelRange(10, 99),
            ),
            (33, 34),
        )
        bounds = AccountSearchBounds(
            attack=LevelRange(1, 1),
            strength=LevelRange(1, 1),
            ranged=LevelRange(44, 44),
            magic=LevelRange(1, 1),
            prayer=LevelRange(8, 8),
            hitpoints=LevelRange(10, 99),
            combat_minimum=30,
            combat_maximum=30,
        )
        self.assertEqual(
            list(enumerate_standard_f2p_account_states(bounds, self.mechanics)),
            [probe],
        )

    def test_direct_generator_matches_old_generate_then_filter_result(self) -> None:
        bounds = AccountSearchBounds(
            attack=LevelRange(35, 40),
            strength=LevelRange(20, 30),
            ranged=LevelRange(30, 40),
            magic=LevelRange(1, 2),
            prayer=LevelRange(1, 8),
            hitpoints=LevelRange(25, 45),
            combat_minimum=25,
            combat_maximum=35,
        )
        old = {
            account
            for account in enumerate_account_states(bounds, self.mechanics)
            if standard_f2p_hitpoints_achievable(account, self.mechanics)
        }
        direct = set(enumerate_standard_f2p_account_states(bounds, self.mechanics))
        self.assertEqual(direct, old)
        self.assertTrue(all(standard_f2p_hitpoints_achievable(account, self.mechanics) for account in direct))
