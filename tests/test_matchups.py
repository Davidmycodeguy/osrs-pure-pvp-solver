import unittest
from fractions import Fraction

from pure_solver.duel import DuelActor, DuelRules, DuelSimulator, DuelState, ScriptedPolicy, TickIntent
from pure_solver.evaluation import MatchupResult
from pure_solver.events import TerminalStatus
from pure_solver.inventory import InventoryEntry, InventoryState
from pure_solver.matchups import (
    adaptive_matchup,
    build_matchup_matrix,
    paired_common_random_comparison,
    simulate_matchup_with_resources,
)
from pure_solver.profiles import AttackProfile, VerifiedAttackTiming
from pure_solver.ruleset import load_ruleset


def _result(win: float, loss: float, samples: int = 10_000) -> MatchupResult:
    wins = round(win * samples)
    losses = round(loss * samples)
    draws = samples - wins - losses
    return MatchupResult(
        wins,
        losses,
        draws,
        samples,
        wins / samples,
        losses / samples,
        draws / samples,
        0.001,
        (max(0.0, win - 0.01), min(1.0, win + 0.01)),
        1,
    )


class MatchupEvaluationTests(unittest.TestCase):
    def test_matchup_resource_output_reports_all_food_consumed(self) -> None:
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        consumables = {item["consumable_id"]: item for item in ruleset.consumables}
        timing = VerifiedAttackTiming(4, {1: 0}, 1, 1, ("fixture",), "verified")
        profile = AttackProfile(1, "slash", 1, 0, Fraction(1), 1, timing, True, ("fixture",))
        rules = DuelRules(
            "actions-before-new-impacts-v1",
            TerminalStatus.DRAW,
            3,
            True,
            ("fixture",),
            "verified",
        )
        simulator = DuelSimulator(rules, consumables)

        def state_factory() -> DuelState:
            player = DuelActor(
                1,
                20,
                1,
                {1: profile},
                attack_ready_tick=99,
                inventory=InventoryState((InventoryEntry("anchovy_pizza", "full"),)),
            )
            opponent = DuelActor(20, 20, 1, {1: profile}, attack_ready_tick=99)
            return DuelState(0, player, opponent, 1)

        result = simulate_matchup_with_resources(
            simulator,
            state_factory,
            ScriptedPolicy({0: TickIntent(eat="anchovy_pizza"), 1: TickIntent(eat="anchovy_pizza")}),
            ScriptedPolicy({}),
            samples=10,
            seed=5,
        )
        self.assertEqual(result.player_resources.usage_histogram_by_item["anchovy_pizza"], {2: 10})
        self.assertEqual(result.player_resources.reached_maximum_rate_by_item["anchovy_pizza"], 1.0)
        self.assertEqual(result.player_resources.all_food_consumed_rate, 1.0)
        self.assertIsNone(result.opponent_resources.all_food_consumed_rate)

    def test_paired_identical_candidates_have_zero_variance(self) -> None:
        comparison = paired_common_random_comparison(
            lambda seed: (seed % 3) - 1,
            lambda seed: (seed % 3) - 1,
            samples=1_000,
            seed=42,
        )
        self.assertEqual(comparison.mean_payoff_difference, 0.0)
        self.assertEqual(comparison.standard_error, 0.0)

    def test_adaptive_sampling_stops_when_interval_resolves_order(self) -> None:
        adaptive = adaptive_matchup(
            lambda samples, seed: _result(0.65, 0.35, samples=samples),
            sample_schedule=(100, 1_000, 10_000),
            seed=7,
        )
        self.assertTrue(adaptive.ordering_resolved)
        self.assertEqual(len(adaptive.stages), 1)

    def test_matchup_matrix_keeps_directional_results(self) -> None:
        outcomes = {
            ("a", "a"): _result(0.5, 0.5),
            ("a", "b"): _result(0.7, 0.3),
            ("b", "a"): _result(0.2, 0.8),
            ("b", "b"): _result(0.5, 0.5),
        }
        matrix = build_matchup_matrix(("a", "b"), lambda row, column: outcomes[(row, column)])
        self.assertAlmostEqual(matrix.payoff[0][1], 0.4)
        self.assertAlmostEqual(matrix.payoff[1][0], -0.6)
