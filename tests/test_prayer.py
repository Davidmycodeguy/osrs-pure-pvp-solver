import unittest
from fractions import Fraction
from pathlib import Path

from pure_solver.errors import DataUnavailableError
from pure_solver.prayer_book import PrayerBook
from pure_solver.ruleset import load_ruleset

MECHANICS = load_ruleset(Path("rulesets/osrs-f2p-v1")).mechanics
BOOK = PrayerBook.from_mechanics(MECHANICS)


class PrayerBookTests(unittest.TestCase):
    def test_catalog_loads_verified_f2p_pvp_prayers(self) -> None:
        protect = BOOK.get("protect_from_melee")
        mystic = BOOK.get("mystic_might")
        self.assertEqual(protect.level, 43)
        self.assertEqual(protect.drain_effect, 12)
        self.assertEqual(protect.protection_style, "melee")
        self.assertEqual(mystic.level, 45)
        self.assertEqual(mystic.magic_attack_multiplier, Fraction(115, 100))
        self.assertEqual(mystic.magic_damage_multiplier, Fraction(102, 100))

    def test_melee_attack_and_strength_stack_but_ranged_replaces_them(self) -> None:
        state = BOOK.empty_state(prayer_level=44)
        state = BOOK.activate(state, "ultimate_strength")
        state = BOOK.activate(state, "incredible_reflexes")
        self.assertEqual(set(state.active_prayer_ids), {"ultimate_strength", "incredible_reflexes"})
        modifiers = BOOK.modifiers(state)
        self.assertEqual(modifiers.melee_strength, Fraction(115, 100))
        self.assertEqual(modifiers.melee_attack, Fraction(115, 100))

        state = BOOK.activate(state, "eagle_eye")
        self.assertEqual(state.active_prayer_ids, ("eagle_eye",))
        modifiers = BOOK.modifiers(state)
        self.assertEqual(modifiers.ranged_attack, Fraction(115, 100))
        self.assertEqual(modifiers.ranged_strength, Fraction(115, 100))
        self.assertEqual(modifiers.melee_attack, Fraction(1))

    def test_locked_or_unfunded_prayers_fail_closed(self) -> None:
        state = BOOK.empty_state(prayer_level=31, current_points=31)
        with self.assertRaises(DataUnavailableError):
            BOOK.activate(state, "protect_from_melee")
        drained = BOOK.empty_state(prayer_level=31, current_points=0)
        with self.assertRaises(DataUnavailableError):
            BOOK.activate(drained, "ultimate_strength")

    def test_drain_counter_matches_published_three_second_rate(self) -> None:
        state = BOOK.empty_state(prayer_level=40)
        state = BOOK.activate(state, "protect_from_magic")
        for _ in range(4):
            state = BOOK.advance_tick(state, prayer_bonus=0)
        self.assertEqual(state.current_points, 40)
        self.assertEqual(state.drain_counter, 48)
        state = BOOK.advance_tick(state, prayer_bonus=0)
        self.assertEqual(state.current_points, 39)
        self.assertEqual(state.drain_counter, 0)

    def test_flicking_resets_counter_when_all_prayers_turn_off(self) -> None:
        state = BOOK.empty_state(prayer_level=43)
        for _ in range(10):
            state = BOOK.activate(state, "protect_from_melee")
            state = BOOK.advance_tick(state)
            state = BOOK.deactivate(state, "protect_from_melee")
        self.assertEqual(state.current_points, 43)
        self.assertEqual(state.drain_counter, 0)
        self.assertEqual(state.active_prayer_ids, ())

    def test_protection_reduces_player_damage_without_touching_accuracy(self) -> None:
        state = BOOK.empty_state(prayer_level=43)
        state = BOOK.activate(state, "protect_from_magic")
        self.assertEqual(
            BOOK.damage_taken_multiplier(state, "magic", attacker_is_player=True),
            Fraction(3, 5),
        )
        self.assertEqual(
            BOOK.damage_taken_multiplier(state, "magic", attacker_is_player=False),
            Fraction(0),
        )
        self.assertEqual(
            BOOK.damage_taken_multiplier(state, "melee", attacker_is_player=True),
            Fraction(1),
        )
        self.assertFalse(BOOK.protection_affects_accuracy)
