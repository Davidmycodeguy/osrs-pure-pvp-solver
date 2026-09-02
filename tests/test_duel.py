import unittest
from fractions import Fraction

from pure_solver.duel import (
    AlwaysAttackPolicy,
    DuelActor,
    DuelRules,
    DuelSimulator,
    DuelState,
    PublicPendingHit,
    RestrictedPolicy,
    ScriptedPolicy,
    TickIntent,
    TimedWeaponSwitchPolicy,
)
from pure_solver.errors import DataUnavailableError
from pure_solver.events import TerminalStatus
from pure_solver.inventory import InventoryEntry, InventoryState
from pure_solver.profiles import (
    AttackProfile,
    MeleeProfileInput,
    TargetDefence,
    VerifiedAttackTiming,
    build_melee_profile,
)
from pure_solver.ruleset import load_ruleset


def _profile(weapon_id: int, damage_type: str, cooldown: int, delays: dict[int, int]) -> AttackProfile:
    timing = VerifiedAttackTiming(cooldown, delays, min(delays), max(delays), ("synthetic-test-evidence",), "verified")
    return AttackProfile(
        weapon_id=weapon_id,
        damage_type=damage_type,
        attack_roll=1,
        defence_roll=0,
        hit_chance=Fraction(1),
        max_hit=1,
        timing=timing,
        successful_zero_becomes_one=True,
        formula_versions=("synthetic-test",),
    )


class DuelSimulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = DuelRules(
            "actions-before-new-impacts-v1",
            TerminalStatus.DRAW,
            20,
            True,
            ("synthetic-test-evidence",),
            "verified",
        )

    def test_delayed_ranged_and_melee_hits_stack_on_one_tick(self) -> None:
        ranged = _profile(1, "ranged", 3, {1: 3})
        melee = _profile(2, "slash", 4, {1: 0})
        idle = _profile(3, "slash", 20, {1: 0})
        state = DuelState(
            tick=0,
            player=DuelActor(10, 10, 1, {1: ranged, 2: melee}),
            opponent=DuelActor(2, 2, 3, {3: idle}, attack_ready_tick=99),
            distance=1,
        )
        result = DuelSimulator(self.rules).run(
            state,
            TimedWeaponSwitchPolicy(1, 2, switch_tick=3),
            AlwaysAttackPolicy(),
            seed=7,
        )
        self.assertIs(result.terminal_status, TerminalStatus.PLAYER_WIN)
        tick_three_damage = [entry for entry in result.history if entry.startswith("3:opponent:damage")]
        self.assertEqual(len(tick_three_damage), 2)
        self.assertTrue(any("3:player:switch:2" == entry for entry in result.history))

    def test_policy_view_does_not_expose_pending_damage_amount(self) -> None:
        self.assertNotIn("amount", PublicPendingHit.__dataclass_fields__)

    def test_pid_priority_prevents_lower_priority_lethal_hit(self) -> None:
        profile = _profile(1, "slash", 4, {1: 0})
        result = DuelSimulator(self.rules).run(
            DuelState(0, DuelActor(1, 1, 1, {1: profile}), DuelActor(1, 1, 1, {1: profile}), 1),
            AlwaysAttackPolicy(),
            AlwaysAttackPolicy(),
            seed=1,
        )
        self.assertIs(result.terminal_status, TerminalStatus.PLAYER_WIN)
        self.assertEqual([entry for entry in result.history if ":player:damage:" in entry], [])

    def test_ruleset_timing_pipeline_resolves_player_priority(self) -> None:
        rules = DuelRules.from_mechanics(
            load_ruleset("rulesets/osrs-f2p-v1").mechanics,
            maximum_ticks=20,
            switch_and_attack_same_tick=True,
        )
        self.assertEqual(rules.pipeline_id, "actions-before-new-impacts-v1")
        self.assertIs(rules.simultaneous_ko, TerminalStatus.PLAYER_WIN)
        self.assertEqual(rules.priority_order, ("player", "opponent"))

    def test_verified_pizza_states_change_eat_and_attack_readiness(self) -> None:
        profile = _profile(1, "slash", 4, {1: 0})
        actor = DuelActor(1, 20, 1, {1: profile}, inventory=InventoryState((InventoryEntry("anchovy_pizza", "full"),)))
        opponent = DuelActor(20, 20, 1, {1: profile}, attack_ready_tick=99)
        consumables = {
            "anchovy_pizza": {
                "status": "verified",
                "availability_scope": "f2p_standard_world",
                "source_ids": ["fixture"],
                "transitions": {
                    "full": {"next_state": "half", "healing": 9, "eat_delay_ticks": 1, "attack_delay_ticks": 3},
                    "half": {"next_state": None, "healing": 9, "eat_delay_ticks": 2, "attack_delay_ticks": 3},
                },
            }
        }
        result = DuelSimulator(self.rules, consumables).run(
            DuelState(0, actor, opponent, 1),
            ScriptedPolicy({0: TickIntent(eat="anchovy_pizza"), 1: TickIntent(eat="anchovy_pizza")}),
            ScriptedPolicy({}),
            seed=1,
        )
        self.assertEqual(result.player.hp, 19)
        self.assertEqual(result.player.inventory.entries, ())
        self.assertEqual(result.player.eat_ready_tick, 3)
        self.assertEqual(result.player.attack_ready_tick, 6)

    def test_restricted_policy_eats_then_uses_ko_threshold(self) -> None:
        profile = _profile(1, "slash", 4, {1: 0})
        ko = _profile(2, "slash", 7, {1: 0})
        view_actor = DuelActor(
            5,
            20,
            1,
            {1: profile, 2: ko},
            inventory=InventoryState((InventoryEntry("swordfish", "whole"),)),
        )
        opponent = DuelActor(4, 20, 1, {1: profile})
        simulator = DuelSimulator(self.rules)
        view = simulator._view(DuelState(0, view_actor, opponent, 1), "player")
        policy = RestrictedPolicy(1, 2, eat_threshold=6, ko_threshold=5)
        self.assertEqual(policy.choose(view), TickIntent(eat="swordfish"))
        healthy_view = view.__class__(**{**view.__dict__, "own_hp": 20})
        self.assertEqual(policy.choose(healthy_view), TickIntent(switch_to=2, attack=True))

    def test_strength_potion_changes_melee_max_hit_and_preserves_decay_phase(self) -> None:
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        consumables = {item["consumable_id"]: item for item in ruleset.consumables}
        timing = VerifiedAttackTiming(4, {1: 0}, 1, 1, ("fixture",), "verified")
        profile = build_melee_profile(
            ruleset.mechanics,
            MeleeProfileInput(1333, "slash", 40, 40, 45, 44, timing, strength_style_bonus=3),
            TargetDefence(1, 0),
        )
        player = DuelActor(
            20,
            20,
            1333,
            {1333: profile},
            inventory=InventoryState((InventoryEntry("strength_potion", "4_dose"),)),
            base_strength=40,
            visible_strength=40,
            combat_boost_decay_remaining=2,
        )
        opponent = DuelActor(20, 20, 1333, {1333: profile}, attack_ready_tick=99)
        rules = DuelRules(
            "actions-before-new-impacts-v1",
            TerminalStatus.DRAW,
            1,
            True,
            ("fixture",),
            "verified",
        )
        simulator = DuelSimulator(rules, consumables, ruleset.mechanics)
        result = simulator.run(
            DuelState(0, player, opponent, 1),
            ScriptedPolicy({0: TickIntent(drink="strength_potion", attack=True)}),
            ScriptedPolicy({}),
            seed=2,
        )
        self.assertEqual(result.player.visible_strength, 47)
        self.assertEqual(result.player.combat_boost_decay_remaining, 1)
        self.assertEqual(result.player.drink_ready_tick, 3)
        self.assertEqual(result.player.inventory.entries, (InventoryEntry("strength_potion", "3_dose"),))
        self.assertEqual(simulator._profile_for_actor(result.player).max_hit, 10)

    def test_food_and_strength_potion_can_be_consumed_same_tick(self) -> None:
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        consumables = {item["consumable_id"]: item for item in ruleset.consumables}
        profile = _profile(1, "slash", 4, {1: 0})
        player = DuelActor(
            1,
            20,
            1,
            {1: profile},
            attack_ready_tick=99,
            inventory=InventoryState(
                (
                    InventoryEntry("strength_potion", "4_dose"),
                    InventoryEntry("swordfish", "whole"),
                )
            ),
            base_strength=40,
            visible_strength=40,
            combat_boost_decay_remaining=50,
        )
        opponent = DuelActor(20, 20, 1, {1: profile}, attack_ready_tick=99)
        simulator = DuelSimulator(self.rules, consumables, ruleset.mechanics)
        result = simulator.run(
            DuelState(0, player, opponent, 1),
            ScriptedPolicy({0: TickIntent(eat="swordfish", drink="strength_potion")}),
            ScriptedPolicy({}),
            seed=1,
        )
        self.assertEqual(result.player.hp, 15)
        self.assertEqual(result.player.visible_strength, 47)
        self.assertEqual(result.player.eat_ready_tick, 3)
        self.assertEqual(result.player.drink_ready_tick, 3)

    def test_strength_repot_restores_static_cap_without_resetting_cycle(self) -> None:
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        consumables = {item["consumable_id"]: item for item in ruleset.consumables}
        profile = _profile(1, "slash", 4, {1: 0})
        actor = DuelActor(
            20,
            20,
            1,
            {1: profile},
            attack_ready_tick=99,
            inventory=InventoryState((InventoryEntry("strength_potion", "4_dose"),)),
            base_strength=40,
            visible_strength=46,
            combat_boost_decay_remaining=50,
        )
        result = DuelSimulator(self.rules, consumables, ruleset.mechanics).run(
            DuelState(0, actor, DuelActor(20, 20, 1, {1: profile}, attack_ready_tick=99), 1),
            ScriptedPolicy({0: TickIntent(drink="strength_potion")}),
            ScriptedPolicy({}),
            seed=1,
        )
        self.assertEqual(result.player.visible_strength, 47)
        self.assertEqual(result.player.combat_boost_decay_remaining, 30)
        self.assertEqual(result.player.inventory.entries, (InventoryEntry("strength_potion", "3_dose"),))

    def test_strength_boost_decay_uses_continuous_100_tick_cycle(self) -> None:
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        profile = _profile(1, "slash", 4, {1: 0})
        player = DuelActor(
            20,
            20,
            1,
            {1: profile},
            attack_ready_tick=99,
            base_strength=40,
            visible_strength=47,
            combat_boost_decay_remaining=1,
        )
        opponent = DuelActor(20, 20, 1, {1: profile}, attack_ready_tick=99)
        one_tick_rules = DuelRules(
            "actions-before-new-impacts-v1",
            TerminalStatus.DRAW,
            1,
            True,
            ("fixture",),
            "verified",
        )
        result = DuelSimulator(one_tick_rules, mechanics=ruleset.mechanics).run(
            DuelState(0, player, opponent, 1), ScriptedPolicy({}), ScriptedPolicy({}), seed=1
        )
        self.assertEqual(result.player.visible_strength, 46)
        self.assertEqual(result.player.combat_boost_decay_remaining, 100)

    def test_unverified_duel_ordering_is_rejected(self) -> None:
        rules = DuelRules("actions-before-new-impacts-v1", TerminalStatus.DRAW, 20, True, (), "unverified")
        with self.assertRaises(Exception):
            DuelSimulator(rules)

    def test_illegal_attack_distance_invalidates_duel(self) -> None:
        melee = _profile(1, "slash", 4, {1: 0})
        actor = DuelActor(10, 10, 1, {1: melee})
        with self.assertRaises(DataUnavailableError):
            DuelSimulator(self.rules).run(
                DuelState(0, actor, actor, distance=2),
                AlwaysAttackPolicy(),
                AlwaysAttackPolicy(),
                seed=1,
            )

    def test_weapon_switch_does_not_reset_existing_attack_cooldown(self) -> None:
        fast = _profile(1, "slash", 4, {1: 0})
        slow = _profile(2, "slash", 7, {1: 0})
        actor = DuelActor(20, 20, 2, {1: fast, 2: slow}, attack_ready_tick=7)
        switched, changed = DuelSimulator._switch(actor, 1)
        self.assertTrue(changed)
        self.assertEqual(switched.active_weapon_id, 1)
        self.assertEqual(switched.attack_ready_tick, 7)
