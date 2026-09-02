import unittest
from fractions import Fraction
from pathlib import Path

from pure_solver.accounts import AccountState, LevelRange
from pure_solver.frontier import (
    OffensiveTarget,
    _candidate_for_kit,
    clear_frontier_caches,
    frontier_cache_sizes,
    prune_dominated_account_states,
    solve_verified_offense,
)
from pure_solver.kits import CombatKit
from pure_solver.legality import EquipmentItem, Loadout
from pure_solver.prayers import best_melee_prayer_set, best_ranged_prayer_set, protection_prayer, relevant_prayer_levels
from pure_solver.ruleset import load_ruleset

RULESET = load_ruleset(Path("rulesets/osrs-f2p-v1"))


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


class PrayerAndFrontierTests(unittest.TestCase):
    def test_frontier_rejects_combat_below_thirty(self) -> None:
        with self.assertRaises(ValueError):
            solve_verified_offense(
                RULESET,
                attack_range=LevelRange(40, 40),
                strength_range=LevelRange(40, 40),
                ranged_range=LevelRange(1, 1),
                hitpoints_range=LevelRange(40, 40),
                combat_minimum=29,
                combat_maximum=40,
                top=1,
            )

    def test_frontier_reuses_inventory_and_style_caches(self) -> None:
        clear_frontier_caches()
        kwargs = dict(
            attack_range=LevelRange(40, 40),
            strength_range=LevelRange(40, 40),
            ranged_range=LevelRange(1, 1),
            prayer_maximum=4,
            hitpoints_range=LevelRange(40, 40),
            combat_minimum=30,
            combat_maximum=40,
            top=1,
        )
        first = solve_verified_offense(RULESET, **kwargs)
        sizes = dict(frontier_cache_sizes())
        second = solve_verified_offense(RULESET, **kwargs)
        self.assertEqual(first["top_overall"], second["top_overall"])
        self.assertEqual(dict(frontier_cache_sizes()), sizes)

    def test_account_pareto_prunes_only_same_cost_and_unlock_group(self) -> None:
        items = tuple(EquipmentItem.from_document(item) for item in RULESET.items)
        accounts = (
            AccountState(40, 39, 1, 1, 1, 40),
            AccountState(40, 40, 1, 1, 1, 40),
            AccountState(40, 40, 1, 1, 1, 41),
        )
        # Only compare states sharing exact combat cost, HP, Prayer, and unlocks.
        efficient = prune_dominated_account_states(accounts, items, RULESET)
        ids = {account.canonical_id for account in efficient}
        self.assertIn(accounts[2].canonical_id, ids)
        if accounts[0].combat_level(RULESET.mechanics) == accounts[1].combat_level(RULESET.mechanics):
            self.assertNotIn(accounts[0].canonical_id, ids)

    def test_verified_prayer_tables_resolve_best_f2p_boosts(self) -> None:
        melee = best_melee_prayer_set(RULESET.mechanics, 31)
        ranged = best_ranged_prayer_set(RULESET.mechanics, 26)
        eagle_eye = best_ranged_prayer_set(RULESET.mechanics, 44)
        self.assertEqual(melee.attack_multiplier, Fraction(11, 10))
        self.assertEqual(melee.strength_multiplier, Fraction(23, 20))
        self.assertEqual(melee.prayer_ids, ("improved_reflexes", "ultimate_strength"))
        self.assertEqual(ranged.multiplier, Fraction(11, 10))
        self.assertEqual(ranged.prayer_ids, ("hawk_eye",))
        self.assertEqual(eagle_eye.multiplier, Fraction(23, 20))
        self.assertEqual(eagle_eye.prayer_ids, ("eagle_eye",))
        self.assertEqual(
            relevant_prayer_levels(RULESET.mechanics),
            (1, 4, 7, 8, 9, 13, 16, 26, 27, 31, 34, 44, 45),
        )
        self.assertEqual(
            relevant_prayer_levels(RULESET.mechanics, include_protection=True),
            (1, 4, 7, 8, 9, 13, 16, 26, 27, 31, 34, 37, 40, 43, 44, 45),
        )
        self.assertEqual(
            relevant_prayer_levels(RULESET.mechanics, include_magic=False),
            (1, 4, 7, 8, 13, 16, 26, 31, 34, 44),
        )

    def test_verified_pvp_protection_uses_forty_percent_player_reduction(self) -> None:
        prayer = protection_prayer(RULESET.mechanics, "melee", 43)
        self.assertIsNotNone(prayer)
        assert prayer is not None
        self.assertEqual(prayer.prayer_id, "protect_from_melee")
        self.assertEqual(prayer.damage_multiplier, Fraction(3, 5))

    def test_solve_verified_offense_ranks_melee_slice_and_tracks_potion_uses(self) -> None:
        result = solve_verified_offense(
            RULESET,
            target=OffensiveTarget(),
            attack_range=LevelRange(40, 40),
            strength_range=LevelRange(40, 40),
            ranged_range=LevelRange(1, 1),
            prayer_maximum=31,
            hitpoints_range=LevelRange(36, 36),
            combat_minimum=30,
            combat_maximum=40,
            top=1,
        )
        candidate = result["top_overall"][0]
        ko_candidate = result["top_by_ko_max_hit"][0]
        self.assertEqual(result["scope"], "verified_offense_frontier_v1")
        self.assertEqual(result["verification"]["status"], "verified_for_closed_form_offense_only")
        self.assertFalse(result["verification"]["full_duel_ranking"])
        self.assertFalse(result["verification"]["catalog_complete"])
        self.assertIn("partial catalog", result["verification"]["catalog_warning"])
        self.assertEqual(
            result["search"]["dominated_accounts_pruned"],
            result["search"]["achievable_accounts"] - result["search"]["pareto_accounts"],
        )
        self.assertEqual(candidate["kit"]["primary_weapon"], "Rune scimitar")
        self.assertTrue(candidate["primary"]["strength_potion"])
        self.assertEqual(
            candidate["inventory_frontier"]["best_total_actions"]["maximum_actions_by_item"]["strength_potion"], 4
        )
        # Scimitar + Mooleta to a 2h switch needs room for both unequipped
        # one-handed items, leaving 26 inventory slots.
        self.assertEqual(candidate["kit"]["available_inventory_slots"], 26)
        self.assertEqual(ko_candidate["kit"]["ko_weapon"], "Rune 2h sword")
        self.assertEqual(ko_candidate["kit"]["available_inventory_slots"], 26)

    def test_candidate_uses_full_melee_loadout_bonuses(self) -> None:
        account = AccountState(40, 40, 1, 1, 1, 40)
        weapon = _item(
            item_id=20,
            name="Slash weapon",
            slot="weapon",
            attack_speed=4,
            attack_range=1,
            attack_styles=["accurate_slash"],
            bonuses={"attack_slash": 12, "melee_strength": 12},
        )
        body = _item(item_id=21, slot="body", name="Body", bonuses={"attack_slash": 18, "melee_strength": 20})
        baseline = _candidate_for_kit(
            RULESET,
            account,
            CombatKit(primary_loadout=Loadout((weapon,)), ko_loadout=Loadout((weapon,))),
            OffensiveTarget(),
            strength_potion=False,
        )
        upgraded = _candidate_for_kit(
            RULESET,
            account,
            CombatKit(primary_loadout=Loadout((weapon, body)), ko_loadout=Loadout((weapon, body))),
            OffensiveTarget(),
            strength_potion=False,
        )
        self.assertGreater(upgraded.primary.profile.attack_roll, baseline.primary.profile.attack_roll)
        self.assertGreater(upgraded.primary.profile.max_hit, baseline.primary.profile.max_hit)

    def test_candidate_uses_full_ranged_loadout_bonuses(self) -> None:
        account = AccountState(1, 1, 40, 1, 1, 40)
        bow = _item(
            item_id=30,
            name="Bow",
            slot="2h",
            two_handed=True,
            attack_speed=4,
            attack_range=7,
            attack_styles=["accurate_ranged"],
            ammo_ids=[31, 32],
            bonuses={"attack_ranged": 20},
        )
        weak_arrows = _item(item_id=31, slot="ammo", name="Weak arrows", bonuses={"ranged_strength": 0})
        strong_arrows = _item(item_id=32, slot="ammo", name="Strong arrows", bonuses={"ranged_strength": 31})
        weak = _candidate_for_kit(
            RULESET,
            account,
            CombatKit(primary_loadout=Loadout((bow, weak_arrows)), ko_loadout=Loadout((bow, weak_arrows))),
            OffensiveTarget(),
            strength_potion=False,
        )
        strong = _candidate_for_kit(
            RULESET,
            account,
            CombatKit(primary_loadout=Loadout((bow, strong_arrows)), ko_loadout=Loadout((bow, strong_arrows))),
            OffensiveTarget(),
            strength_potion=False,
        )
        self.assertGreater(strong.primary.profile.max_hit, weak.primary.profile.max_hit)
