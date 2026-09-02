import unittest
from fractions import Fraction
from pathlib import Path

from pure_solver.errors import VerifiedMechanicMissingError
from pure_solver.profiles import (
    MeleeProfileInput,
    RangedProfileInput,
    TargetDefence,
    VerifiedAttackTiming,
    build_melee_offensive_profile,
    build_melee_profile,
    build_ranged_offensive_profile,
    build_ranged_profile,
)
from pure_solver.ruleset import load_ruleset

MECHANICS = load_ruleset(Path("rulesets/osrs-f2p-v1")).mechanics


class AttackProfileTests(unittest.TestCase):
    def test_player_defence_and_melee_profile_are_formula_derived(self) -> None:
        timing = VerifiedAttackTiming(4, {1: 0}, 1, 1, ("synthetic-test-evidence",), "verified")
        profile = build_melee_profile(
            MECHANICS,
            MeleeProfileInput(
                weapon_id=1333,
                attack_type="slash",
                attack_level=40,
                strength_level=40,
                attack_bonus=45,
                strength_bonus=44,
                timing=timing,
                strength_style_bonus=3,
            ),
            TargetDefence(defence_level=1, defence_bonus=0),
        )
        self.assertEqual(profile.attack_roll, 48 * 109)
        self.assertEqual(profile.defence_roll, 9 * 64)
        self.assertEqual(profile.max_hit, 9)
        self.assertEqual(profile.hit_chance, Fraction(1) - Fraction(578, 2 * (profile.attack_roll + 1)))

    def test_ranged_profile_preserves_formula_flooring(self) -> None:
        timing = VerifiedAttackTiming(3, {3: 1}, 1, 7, ("synthetic-test-evidence",), "verified")
        profile = build_ranged_profile(
            MECHANICS,
            RangedProfileInput(
                weapon_id=841,
                ranged_level=40,
                ranged_attack_bonus=29,
                ranged_strength_bonus=31,
                timing=timing,
            ),
            TargetDefence(defence_level=1, defence_bonus=0),
        )
        self.assertEqual(profile.attack_roll, 48 * 93)
        self.assertEqual(profile.max_hit, 7)
        self.assertEqual(profile.timing.impact_delay(3), 1)

    def test_offensive_profiles_compute_exact_expected_damage_per_tick(self) -> None:
        melee = build_melee_offensive_profile(
            MECHANICS,
            MeleeProfileInput(
                weapon_id=1333,
                attack_type="slash",
                attack_level=40,
                strength_level=40,
                attack_bonus=45,
                strength_bonus=44,
                timing=None,  # type: ignore[arg-type]
                strength_style_bonus=3,
            ),
            TargetDefence(defence_level=1, defence_bonus=0),
            cooldown_ticks=4,
        )
        ranged = build_ranged_offensive_profile(
            MECHANICS,
            RangedProfileInput(
                weapon_id=853,
                ranged_level=40,
                ranged_attack_bonus=29,
                ranged_strength_bonus=31,
                timing=None,  # type: ignore[arg-type]
            ),
            TargetDefence(defence_level=1, defence_bonus=0),
            cooldown_ticks=3,
        )
        self.assertEqual(melee.max_hit, 9)
        self.assertEqual(melee.expected_damage_per_tick, Fraction(28428, 26165))
        self.assertEqual(ranged.max_hit, 7)
        self.assertEqual(ranged.expected_damage_per_tick, Fraction(5046, 4465))

    def test_offensive_profile_applies_pvp_protection_after_max_hit_floor(self) -> None:
        protected = build_melee_offensive_profile(
            MECHANICS,
            MeleeProfileInput(
                weapon_id=1319,
                attack_type="slash",
                attack_level=40,
                strength_level=60,
                attack_bonus=69,
                strength_bonus=70,
                timing=None,  # type: ignore[arg-type]
                strength_style_bonus=3,
            ),
            TargetDefence(defence_level=1, defence_bonus=0),
            cooldown_ticks=7,
            damage_multiplier=Fraction(3, 5),
        )
        self.assertEqual(protected.max_hit, 9)

    def test_unverified_timing_blocks_profile_construction(self) -> None:
        timing = VerifiedAttackTiming(4, {1: 0}, 1, 1, (), "unverified")
        with self.assertRaises(VerifiedMechanicMissingError):
            build_melee_profile(
                MECHANICS,
                MeleeProfileInput(1, "slash", 1, 1, 0, 0, timing),
                TargetDefence(1, 0),
            )
