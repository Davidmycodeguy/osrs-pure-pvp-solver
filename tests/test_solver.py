import unittest
from dataclasses import replace
from unittest.mock import patch

from pure_solver.accounts import AccountState
from pure_solver.duel import DuelRules, DuelSimulator
from pure_solver.events import TerminalStatus
from pure_solver.kits import CombatKit, generate_combat_kits
from pure_solver.legality import EquipmentItem, Loadout
from pure_solver.matchups import ResourceMatchupResult
from pure_solver.ruleset import load_ruleset
from pure_solver.solver import (
    BuildPlan,
    InventoryPlan,
    build_plan_actor,
    build_supported_profile,
    default_opening_distances,
    materialize_supported_strategy_pool,
    optimize_supported_matchup,
    resolve_supported_style,
    supported_preflight,
    supported_styles_for_item,
)

RULESET = load_ruleset("rulesets/osrs-f2p-v1")
ITEMS = tuple(EquipmentItem.from_document(item) for item in RULESET.items)


def _kit(account: AccountState, primary: int, ko: int):
    search = generate_combat_kits(account, ITEMS)
    return next(kit for kit in search.kits if (kit.primary_weapon.item_id == primary and kit.ko_weapon.item_id == ko))


def _item(item_id: int) -> EquipmentItem:
    return next(item for item in ITEMS if item.item_id == item_id)


class SupportedSolverTests(unittest.TestCase):
    def test_supported_preflight_allows_current_verified_slice(self) -> None:
        supported_preflight(RULESET)

    def test_shortbow_only_keeps_verified_rapid_style(self) -> None:
        shortbow = next(item for item in ITEMS if item.item_id == 853)
        self.assertEqual(
            [style.style_id for style in supported_styles_for_item(shortbow)],
            ["rapid_ranged"],
        )

    def test_unverified_crossbow_timing_is_not_materialized(self) -> None:
        crossbow = next(item for item in ITEMS if item.weapon_type == "crossbow")
        self.assertEqual(supported_styles_for_item(crossbow), ())

    def test_supported_melee_timing_is_ruleset_defined(self) -> None:
        account = AccountState(40, 40, 1, 1, 1, 40)
        scimitar = next(item for item in ITEMS if item.item_id == 1333)
        profile = build_supported_profile(
            RULESET, account, scimitar, resolve_supported_style(scimitar, "aggressive_slash")
        )
        self.assertEqual(profile.timing.impact_delay_by_distance, {1: 0, 2: 0})

    def test_supported_ranged_timing_is_ruleset_defined(self) -> None:
        account = AccountState(40, 40, 30, 1, 1, 40)
        shortbow = next(item for item in ITEMS if item.item_id == 853)
        profile = build_supported_profile(RULESET, account, shortbow, resolve_supported_style(shortbow, "rapid_ranged"))
        self.assertEqual(profile.timing.impact_delay_by_distance, {2: 3})

    def test_same_weapon_cannot_style_switch_through_weapon_swap(self) -> None:
        account = AccountState(40, 40, 1, 1, 1, 40)
        kit = _kit(account, 1333, 1333)
        with self.assertRaisesRegex(Exception, "cannot change attack styles"):
            build_plan_actor(
                RULESET,
                BuildPlan(
                    account=account,
                    kit=kit,
                    primary_style=resolve_supported_style(kit.primary_weapon, "accurate_slash"),
                    ko_style=resolve_supported_style(kit.ko_weapon, "aggressive_slash"),
                    inventory=InventoryPlan(swordfish=28),
                    opening_distance=default_opening_distances(kit)[0],
                ),
            )

    def test_same_weapon_cannot_hide_an_ammunition_only_switch(self) -> None:
        account = AccountState(40, 40, 40, 1, 1, 40)
        shortbow = _item(853)
        compatible = [item for item in ITEMS if item.slot == "ammo" and item.item_id in shortbow.ammo_ids]
        self.assertTrue(compatible)
        alternate_ammo = replace(compatible[0], item_id=999_001, name="Fixture alternate arrows")
        kit = CombatKit(
            primary_loadout=Loadout((shortbow, compatible[0])),
            ko_loadout=Loadout((shortbow, alternate_ammo)),
        )
        style = resolve_supported_style(shortbow, "rapid_ranged")

        with self.assertRaisesRegex(Exception, "cannot change ammunition"):
            build_plan_actor(
                RULESET,
                BuildPlan(
                    account=account,
                    kit=kit,
                    primary_style=style,
                    ko_style=style,
                    inventory=InventoryPlan(swordfish=27),
                    opening_distance=2,
                ),
            )

    def test_full_loadout_bonuses_increase_melee_attack_roll(self) -> None:
        account = AccountState(40, 40, 1, 1, 1, 40)
        scimitar = _item(1333)
        amulet_of_power = _item(1731)
        profile = build_supported_profile(
            RULESET,
            account,
            scimitar,
            resolve_supported_style(scimitar, "aggressive_slash"),
            equipment_bonuses={
                **scimitar.bonuses,
                **{"attack_slash": scimitar.bonuses["attack_slash"] + amulet_of_power.bonuses["attack_slash"]},
                **{"melee_strength": scimitar.bonuses["melee_strength"] + amulet_of_power.bonuses["melee_strength"]},
            },
        )
        baseline = build_supported_profile(
            RULESET,
            account,
            scimitar,
            resolve_supported_style(scimitar, "aggressive_slash"),
        )
        self.assertGreater(profile.attack_roll, baseline.attack_roll)

    def test_full_loadout_defence_bonuses_change_dynamic_target_defence(self) -> None:
        account = AccountState(40, 40, 1, 1, 1, 40)
        attacker_weapon = _item(1333)
        target_weapon = _item(1333)
        shield = _item(33101)
        amulet_of_power = _item(1731)
        attacker_kit = CombatKit(
            primary_loadout=Loadout((attacker_weapon,)),
            ko_loadout=Loadout((attacker_weapon,)),
        )
        base_target_kit = CombatKit(
            primary_loadout=Loadout((target_weapon,)),
            ko_loadout=Loadout((target_weapon,)),
        )
        tank_target_kit = CombatKit(
            primary_loadout=Loadout((target_weapon, shield, amulet_of_power)),
            ko_loadout=Loadout((target_weapon, shield, amulet_of_power)),
        )
        attacker = build_plan_actor(
            RULESET,
            BuildPlan(
                account=account,
                kit=attacker_kit,
                primary_style=resolve_supported_style(attacker_weapon, "aggressive_slash"),
                ko_style=resolve_supported_style(attacker_weapon, "aggressive_slash"),
                inventory=InventoryPlan(swordfish=28),
                opening_distance=1,
            ),
        )
        base_target = build_plan_actor(
            RULESET,
            BuildPlan(
                account=account,
                kit=base_target_kit,
                primary_style=resolve_supported_style(target_weapon, "accurate_slash"),
                ko_style=resolve_supported_style(target_weapon, "accurate_slash"),
                inventory=InventoryPlan(swordfish=28),
                opening_distance=1,
            ),
        )
        tank_target = build_plan_actor(
            RULESET,
            BuildPlan(
                account=account,
                kit=tank_target_kit,
                primary_style=resolve_supported_style(target_weapon, "accurate_slash"),
                ko_style=resolve_supported_style(target_weapon, "accurate_slash"),
                inventory=InventoryPlan(swordfish=28),
                opening_distance=1,
            ),
        )
        simulator = DuelSimulator(
            DuelRules("actions-before-new-impacts-v1", TerminalStatus.DRAW, 20, True, ("fixture",), "verified"),
            mechanics=RULESET.mechanics,
        )
        profile = attacker.weapons[attacker.active_weapon_id]
        self.assertLess(
            simulator._hit_chance_against(profile, tank_target),
            simulator._hit_chance_against(profile, base_target),
        )

    def test_full_loadout_ranged_ammo_is_counted_once(self) -> None:
        account = AccountState(1, 1, 30, 1, 1, 30)
        shortbow = _item(853)
        coif = _item(1169)
        leather_body = _item(1129)
        leather_chaps = _item(1095)
        leather_vambraces = _item(1063)
        amulet_of_power = _item(1731)
        adamant_arrows = _item(890)
        kit = CombatKit(
            primary_loadout=Loadout(
                (shortbow, coif, amulet_of_power, leather_body, leather_chaps, leather_vambraces, adamant_arrows)
            ),
            ko_loadout=Loadout(
                (shortbow, coif, amulet_of_power, leather_body, leather_chaps, leather_vambraces, adamant_arrows)
            ),
        )
        actor = build_plan_actor(
            RULESET,
            BuildPlan(
                account=account,
                kit=kit,
                primary_style=resolve_supported_style(shortbow, "rapid_ranged"),
                ko_style=resolve_supported_style(shortbow, "rapid_ranged"),
                inventory=InventoryPlan(swordfish=28),
                opening_distance=2,
            ),
        )
        via_equipment = build_supported_profile(
            RULESET,
            account,
            shortbow,
            resolve_supported_style(shortbow, "rapid_ranged"),
            equipment_bonuses=kit.equipped_bonuses("primary"),
        )
        via_legacy_compat = build_supported_profile(
            RULESET,
            account,
            shortbow,
            resolve_supported_style(shortbow, "rapid_ranged"),
            ranged_strength_bonus=adamant_arrows.bonuses["ranged_strength"],
        )
        self.assertEqual(actor.weapons[shortbow.item_id].attack_roll, via_equipment.attack_roll)
        self.assertEqual(actor.weapons[shortbow.item_id].max_hit, via_equipment.max_hit)
        self.assertEqual(via_equipment.max_hit, via_legacy_compat.max_hit)
        self.assertGreater(via_equipment.attack_roll, via_legacy_compat.attack_roll)

    def test_defensive_style_changes_dynamic_target_defence(self) -> None:
        account = AccountState(40, 40, 1, 1, 1, 40)
        attacker_kit = _kit(account, 1333, 1333)
        target_kit = _kit(account, 1333, 1333)
        attacker = build_plan_actor(
            RULESET,
            BuildPlan(
                account=account,
                kit=attacker_kit,
                primary_style=resolve_supported_style(attacker_kit.primary_weapon, "aggressive_slash"),
                ko_style=resolve_supported_style(attacker_kit.ko_weapon, "aggressive_slash"),
                inventory=InventoryPlan(swordfish=28),
                opening_distance=1,
            ),
        )
        accurate_target = build_plan_actor(
            RULESET,
            BuildPlan(
                account=account,
                kit=target_kit,
                primary_style=resolve_supported_style(target_kit.primary_weapon, "accurate_slash"),
                ko_style=resolve_supported_style(target_kit.ko_weapon, "accurate_slash"),
                inventory=InventoryPlan(swordfish=28),
                opening_distance=1,
            ),
        )
        defensive_target = build_plan_actor(
            RULESET,
            BuildPlan(
                account=account,
                kit=target_kit,
                primary_style=resolve_supported_style(target_kit.primary_weapon, "defensive_slash"),
                ko_style=resolve_supported_style(target_kit.ko_weapon, "defensive_slash"),
                inventory=InventoryPlan(swordfish=28),
                opening_distance=1,
            ),
        )
        simulator = DuelSimulator(
            DuelRules("actions-before-new-impacts-v1", TerminalStatus.DRAW, 20, True, ("fixture",), "verified"),
            mechanics=RULESET.mechanics,
        )
        profile = attacker.weapons[attacker.active_weapon_id]
        self.assertLess(
            simulator._hit_chance_against(profile, defensive_target),
            simulator._hit_chance_against(profile, accurate_target),
        )

    def test_supported_matchup_runs_with_verified_projectile_timing(self) -> None:
        account = AccountState(40, 40, 30, 1, 1, 40)
        range_melee = _kit(account, 853, 1319)
        scim_2h = _kit(account, 1333, 1319)
        result = optimize_supported_matchup(
            RULESET,
            BuildPlan(
                account=account,
                kit=range_melee,
                primary_style=resolve_supported_style(range_melee.primary_weapon, "rapid_ranged"),
                ko_style=resolve_supported_style(range_melee.ko_weapon, "aggressive_slash"),
                inventory=InventoryPlan(swordfish=14, anchovy_pizza=12, strength_potion=1),
                opening_distance=2,
            ),
            BuildPlan(
                account=account,
                kit=scim_2h,
                primary_style=resolve_supported_style(scim_2h.primary_weapon, "aggressive_slash"),
                ko_style=resolve_supported_style(scim_2h.ko_weapon, "aggressive_slash"),
                inventory=InventoryPlan(swordfish=14, anchovy_pizza=12, strength_potion=1),
                opening_distance=2,
            ),
            samples=6,
            seed=9,
            maximum_ticks=40,
            maximum_iterations=1,
        )
        self.assertEqual(result.matchup.matchup.trials, 6)

    def test_supported_matchup_normalizes_opening_distance_without_mutating_inputs(self) -> None:
        account = AccountState(40, 40, 30, 1, 1, 40)
        range_melee = _kit(account, 853, 1319)
        scim_2h = _kit(account, 1333, 1319)
        player_plan = BuildPlan(
            account=account,
            kit=range_melee,
            primary_style=resolve_supported_style(range_melee.primary_weapon, "rapid_ranged"),
            ko_style=resolve_supported_style(range_melee.ko_weapon, "aggressive_slash"),
            inventory=InventoryPlan(swordfish=14, anchovy_pizza=12, strength_potion=1),
            opening_distance=2,
        )
        opponent_plan = BuildPlan(
            account=account,
            kit=scim_2h,
            primary_style=resolve_supported_style(scim_2h.primary_weapon, "aggressive_slash"),
            ko_style=resolve_supported_style(scim_2h.ko_weapon, "aggressive_slash"),
            inventory=InventoryPlan(swordfish=14, anchovy_pizza=12, strength_potion=1),
            opening_distance=1,
        )

        def fake_simulation(simulator, state_factory, player_policy, opponent_policy, *, samples, seed):
            state = state_factory()
            matchup = ResourceMatchupResult(
                matchup=replace(
                    simulate_result.matchup,
                    seed=seed,
                    samples=samples,
                ),
                player_resources=simulate_result.player_resources,
                opponent_resources=simulate_result.opponent_resources,
            )
            self.assertEqual(state.distance, 2)
            return matchup

        simulate_result = optimize_supported_matchup(
            RULESET,
            player_plan,
            replace(opponent_plan, opening_distance=2),
            samples=1,
            seed=5,
            maximum_ticks=20,
            maximum_iterations=1,
        ).matchup

        with patch("pure_solver.solver.simulate_matchup_with_resources", side_effect=fake_simulation):
            result = optimize_supported_matchup(
                RULESET,
                player_plan,
                opponent_plan,
                samples=1,
                seed=5,
                maximum_ticks=20,
                maximum_iterations=1,
            )

        self.assertEqual(player_plan.opening_distance, 2)
        self.assertEqual(opponent_plan.opening_distance, 1)
        self.assertEqual(result.matchup.matchup.samples, 1)

    def test_supported_matchup_considers_nonzero_ko_threshold_policy(self) -> None:
        account = AccountState(40, 40, 1, 1, 1, 40)
        kit = _kit(account, 1333, 1319)
        plan = BuildPlan(
            account=account,
            kit=kit,
            primary_style=resolve_supported_style(kit.primary_weapon, "aggressive_slash"),
            ko_style=resolve_supported_style(kit.ko_weapon, "aggressive_slash"),
            inventory=InventoryPlan(swordfish=14, anchovy_pizza=12, strength_potion=1),
            opening_distance=1,
        )
        baseline = optimize_supported_matchup(
            RULESET,
            plan,
            plan,
            samples=1,
            seed=11,
            maximum_ticks=20,
            maximum_iterations=1,
        ).matchup

        def fake_simulation(simulator, state_factory, player_policy, opponent_policy, *, samples, seed):
            player_bonus = 0.7 if player_policy.ko_threshold > 0 else 0.2
            opponent_bonus = 0.15 if opponent_policy.ko_threshold > 0 else 0.0
            win_probability = min(0.99, max(0.01, player_bonus - opponent_bonus + 0.2))
            wins = round(win_probability * samples)
            losses = samples - wins
            return ResourceMatchupResult(
                matchup=replace(
                    baseline.matchup,
                    wins=wins,
                    losses=losses,
                    draws=0,
                    samples=samples,
                    win_probability=wins / samples,
                    loss_probability=losses / samples,
                    draw_probability=0.0,
                    standard_error=0.0,
                    seed=seed,
                ),
                player_resources=baseline.player_resources,
                opponent_resources=baseline.opponent_resources,
            )

        with patch("pure_solver.solver.simulate_matchup_with_resources", side_effect=fake_simulation):
            result = optimize_supported_matchup(
                RULESET,
                plan,
                plan,
                samples=5,
                seed=11,
                maximum_ticks=20,
                maximum_iterations=2,
            )

        self.assertGreater(result.player_policy.policy.ko_threshold, 0)
        self.assertEqual(result.matchup.matchup.samples, 5)

    def test_active_strategy_pool_emits_one_candidate_per_build(self) -> None:
        account = AccountState(40, 40, 1, 1, 1, 40)
        strategies = materialize_supported_strategy_pool(
            RULESET,
            (account,),
            maximum_strategies=256,
        )
        self.assertEqual(
            len(strategies),
            len(
                {
                    (
                        strategy.plan.account.canonical_id,
                        strategy.plan.kit.canonical_id,
                        strategy.plan.primary_style.style_id,
                        strategy.plan.ko_style.style_id,
                        strategy.plan.opening_distance,
                    )
                    for strategy in strategies
                }
            ),
        )
