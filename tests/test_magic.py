import unittest
from fractions import Fraction

from pure_solver.errors import DataUnavailableError, VerifiedMechanicMissingError
from pure_solver.magic import MagicBook, build_magic_attack_profile
from pure_solver.mechanics import ImpactTiming, Mechanic
from pure_solver.ruleset import load_ruleset


class MagicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        self.book = MagicBook.from_mechanics(self.ruleset.mechanics)

    def test_f2p_spell_gates_runes_and_bind_durations(self) -> None:
        available = {spell.spell_id for spell in self.book.available(50)}
        self.assertIn("snare", available)
        self.assertNotIn("earth_blast", available)
        snare = self.book.spells["snare"]
        self.assertEqual(snare.bind_duration_ticks, 16)
        self.assertTrue(snare.can_cast(50, {"water": 4, "earth": 4, "nature": 3}))
        self.assertFalse(snare.can_cast(49, {"water": 4, "earth": 4, "nature": 3}))

    def test_magic_profile_carries_verified_projectile_timing(self) -> None:
        spell = self.book.spells["fire_blast"]
        profile = build_magic_attack_profile(
            self.ruleset.mechanics,
            spell,
            magic_level=59,
            magic_boost=0,
            prayer_multiplier=Fraction(1),
            magic_attack_bonus=10,
            target_defence_roll=640,
        )
        self.assertEqual(profile.max_hit, 16)
        self.assertGreater(profile.attack_roll, profile.defence_roll)
        self.assertGreater(profile.hit_chance, Fraction(1, 2))
        self.assertEqual(profile.timing.impact_delay(7), 5)
        with self.assertRaises(VerifiedMechanicMissingError):
            profile.timing.impact_delay(6)

    def test_impact_timing_requires_complete_nonnegative_table(self) -> None:
        with self.assertRaises(DataUnavailableError):
            ImpactTiming.from_mechanic(
                Mechanic(
                    "fixture.timing",
                    "verified",
                    {"impact_delay_by_distance": {"1": 0, "3": -1}, "minimum_distance": 1, "maximum_distance": 3},
                    "fixture",
                    ("fixture",),
                    (),
                )
            )
