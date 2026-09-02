import random
import unittest
from dataclasses import replace
from fractions import Fraction
from itertools import product
from pathlib import Path

from pure_solver.accounts import AccountSearchBounds, AccountState, LevelRange, enumerate_account_states
from pure_solver.errors import DataUnavailableError, MechanicConflictError
from pure_solver.mechanics import MechanicRegistry
from pure_solver.ruleset import load_ruleset

RULESET = load_ruleset(Path("rulesets/osrs-f2p-v1"))


class RulesetAndFormulaTests(unittest.TestCase):
    def test_ruleset_configures_28_inventory_slots(self) -> None:
        self.assertEqual(RULESET.inventory_slots, 28)
        self.assertEqual(RULESET.reproducibility_metadata["inventory_slots"], 28)
        self.assertEqual(len(RULESET.reproducibility_metadata["consumable_database_hash"]), 64)
        self.assertEqual((RULESET.combat_level_minimum, RULESET.combat_level_maximum), (30, 40))
        self.assertEqual(RULESET.defence_level, 1)

    def test_combat_level_uses_outer_floor(self) -> None:
        level_three = AccountState(1, 1, 1, 1, 1, 10)
        self.assertEqual(level_three.combat_level(RULESET.mechanics), 3)

    def test_compiled_combat_level_matches_formula_ast(self) -> None:
        rng = random.Random(91)
        for _ in range(5_000):
            state = AccountState(
                rng.randint(1, 40),
                rng.randint(1, 60),
                rng.randint(1, 60),
                rng.randint(1, 60),
                rng.randint(1, 43),
                rng.randint(10, 99),
            )
            ast_value = RULESET.mechanics.evaluate(
                "combat_level",
                {
                    "attack": state.attack_level,
                    "strength": state.strength_level,
                    "ranged": state.ranged_level,
                    "magic": state.magic_level,
                    "prayer": state.prayer_level,
                    "hitpoints": state.hitpoints_level,
                    "defence": state.defence_level,
                },
            )
            self.assertEqual(state.combat_level(RULESET.mechanics), int(ast_value))

    def test_effective_strength_preserves_prayer_floor_order(self) -> None:
        result = RULESET.mechanics.evaluate(
            "melee.effective_strength",
            {
                "strength_level": 99,
                "strength_boost": 0,
                "prayer_multiplier": Fraction(115, 100),
                "style_bonus": 3,
            },
        )
        self.assertEqual(result, 124)

    def test_max_hit_uses_exact_integer_form(self) -> None:
        result = RULESET.mechanics.evaluate(
            "melee.max_hit",
            {
                "effective_strength": 51,
                "melee_strength_bonus": 44,
            },
        )
        self.assertEqual(result, 9)

    def test_shortbow_rapid_is_three_ticks(self) -> None:
        self.assertEqual(
            RULESET.mechanics.evaluate("ranged.rapid_attack_cooldown", {"base_attack_speed": 4}),
            3,
        )

    def test_strength_potion_boost_uses_static_level(self) -> None:
        self.assertEqual(
            RULESET.mechanics.evaluate("strength_potion.boost", {"base_strength": 40}),
            7,
        )
        self.assertEqual(RULESET.mechanics.require("boost.combat_decay_interval_ticks").value, 100)
        self.assertEqual(RULESET.mechanics.require("potion.drink_delay_ticks").value, 3)
        self.assertTrue(RULESET.mechanics.require("potion.food_timer_independent").value)

    def test_accuracy_uses_strict_greater_than_branch(self) -> None:
        tie = RULESET.mechanics.evaluate("melee.accuracy", {"attack_roll": 10, "defence_roll": 10})
        higher = RULESET.mechanics.evaluate("melee.accuracy", {"attack_roll": 11, "defence_roll": 10})
        self.assertEqual(tie, Fraction(5, 11))
        self.assertEqual(higher, Fraction(1, 2))

    def test_preflight_accepts_verified_production_timing_mechanics(self) -> None:
        RULESET.preflight()
        for mechanic_id in (
            "tick.pipeline",
            "death.simultaneous_ko",
            "melee.damage_timing",
            "ranged.projectile_timing",
            "magic.projectile_timing",
        ):
            self.assertEqual(RULESET.mechanics.require(mechanic_id).status, "verified")

    def test_pinned_source_archive_matches_ruleset_hashes(self) -> None:
        RULESET.verify_source_archive()

    def test_ruleset_rejects_unscoped_or_members_equipment_before_search(self) -> None:
        unscoped = dict(RULESET.items[0], availability_scope="lms")
        with self.assertRaisesRegex(DataUnavailableError, "standard-world scope"):
            replace(RULESET, items=(unscoped,) + RULESET.items[1:]).verify_catalogs()
        members = dict(RULESET.items[0], members=True)
        with self.assertRaisesRegex(DataUnavailableError, "obtainable F2P"):
            replace(RULESET, items=(members,) + RULESET.items[1:]).verify_catalogs()

    def test_ruleset_rejects_unscoped_consumables_before_search(self) -> None:
        unscoped = dict(RULESET.consumables[0], availability_scope="lms")
        with self.assertRaisesRegex(DataUnavailableError, "standard-world scope"):
            replace(RULESET, consumables=(unscoped,) + RULESET.consumables[1:]).verify_catalogs()

    def test_duplicate_source_or_mechanic_ids_fail_closed(self) -> None:
        source = {
            "source_id": "s",
            "url": "https://example.test",
            "revision": "1",
            "retrieved_at": "2026-01-01T00:00:00Z",
        }
        with self.assertRaises(MechanicConflictError):
            MechanicRegistry.from_document({"sources": [source, source], "mechanics": []})
        mechanic = {"mechanic_id": "m", "status": "verified", "formula_version": "1", "source_ids": ["s"], "value": 1}
        with self.assertRaises(MechanicConflictError):
            MechanicRegistry.from_document({"sources": [source], "mechanics": [mechanic, mechanic]})

    def test_account_search_is_lazy_and_filters_combat_range(self) -> None:
        bounds = AccountSearchBounds(
            attack=LevelRange(1, 1),
            strength=LevelRange(1, 1),
            ranged=LevelRange(1, 1),
            magic=LevelRange(1, 1),
            prayer=LevelRange(1, 1),
            hitpoints=LevelRange(10, 10),
            combat_minimum=3,
            combat_maximum=3,
        )
        candidates = list(enumerate_account_states(bounds, RULESET.mechanics))
        self.assertEqual(candidates, [AccountState(1, 1, 1, 1, 1, 10)])

    def test_pruned_account_search_matches_brute_force(self) -> None:
        bounds = AccountSearchBounds(
            attack=LevelRange(1, 4),
            strength=LevelRange(1, 4),
            ranged=LevelRange(1, 4),
            magic=LevelRange(1, 4),
            prayer=LevelRange(1, 3),
            hitpoints=LevelRange(10, 13),
            combat_minimum=3,
            combat_maximum=6,
        )
        actual = set(enumerate_account_states(bounds, RULESET.mechanics))
        brute = set()
        for attack, strength, ranged, magic, prayer, hitpoints in product(
            bounds.attack.values(),
            bounds.strength.values(),
            bounds.ranged.values(),
            bounds.magic.values(),
            bounds.prayer.values(),
            bounds.hitpoints.values(),
        ):
            state = AccountState(attack, strength, ranged, magic, prayer, hitpoints)
            if bounds.combat_minimum <= state.combat_level(RULESET.mechanics) <= bounds.combat_maximum:
                brute.add(state)
        self.assertEqual(actual, brute)
