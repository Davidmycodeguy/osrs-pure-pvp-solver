import unittest
from fractions import Fraction

from pure_solver.evaluation import (
    DamageDistribution,
    derived_seed,
    monte_carlo,
    solve_zero_sum,
    solve_zero_sum_approximate,
    solve_zero_sum_hybrid,
    wilson_interval,
)
from pure_solver.events import CombatState, FighterState, PendingDamage, TerminalStatus, TickEngine
from pure_solver.mechanics import MechanicRegistry


def _engine() -> TickEngine:
    registry = MechanicRegistry.from_document(
        {
            "sources": [
                {
                    "source_id": "fixture",
                    "url": "https://example.test",
                    "revision": "1",
                    "retrieved_at": "2026-09-01T00:00:00Z",
                }
            ],
            "mechanics": [
                {
                    "mechanic_id": "tick.pipeline",
                    "status": "verified",
                    "formula_version": "fixture",
                    "source_ids": ["fixture"],
                    "value": ["resolve_pending_damage", "record_actions", "check_terminal"],
                },
                {
                    "mechanic_id": "death.simultaneous_ko",
                    "status": "verified",
                    "formula_version": "fixture",
                    "source_ids": ["fixture"],
                    "value": "player_win",
                },
            ],
        }
    )
    return TickEngine(registry)


class EventsAndEvaluationTests(unittest.TestCase):
    def test_same_tick_lethal_damage_uses_verified_pid_priority(self) -> None:
        engine = _engine()
        state = CombatState(7, FighterState(10, 10), FighterState(10, 10))
        state = engine.schedule_damage(state, PendingDamage(7, 0, "opponent", "player", 10, 3))
        state = engine.schedule_damage(state, PendingDamage(7, 1, "player", "opponent", 10, 3))
        result = engine.step(state)
        self.assertIs(result.terminal_status, TerminalStatus.PLAYER_WIN)
        self.assertEqual(result.player.hp, 10)

    def test_player_successful_zero_roll_becomes_one_when_configured(self) -> None:
        distribution = DamageDistribution.from_success_chance(Fraction(1, 2), max_hit=2, player_zero_becomes_one=True)
        self.assertEqual(distribution.probability, {0: Fraction(1, 2), 1: Fraction(1, 3), 2: Fraction(1, 6)})
        self.assertEqual(distribution.expected_damage, Fraction(2, 3))

    def test_seed_derivation_is_stable_and_matchup_specific(self) -> None:
        self.assertEqual(derived_seed(42, "a", "b"), derived_seed(42, "a", "b"))
        self.assertNotEqual(derived_seed(42, "a", "b"), derived_seed(42, "b", "a"))

    def test_monte_carlo_reports_a_confidence_interval(self) -> None:
        result = monte_carlo(lambda rng: "win" if rng.random() < 0.5 else "loss", 20_000, 12)
        self.assertLess(result.confidence_interval_95[0], 0.5)
        self.assertGreater(result.confidence_interval_95[1], 0.5)
        self.assertGreater(result.standard_error, 0)
        lower, upper = wilson_interval(100, 100)
        self.assertAlmostEqual(lower, 0.9630065, places=7)
        self.assertEqual(upper, 1.0)

    def test_zero_sum_solver_finds_rock_paper_scissors_mixture(self) -> None:
        equilibrium = solve_zero_sum([[0, -1, 1], [1, 0, -1], [-1, 1, 0]])
        self.assertEqual(equilibrium.row_strategy, (Fraction(1, 3),) * 3)
        self.assertEqual(equilibrium.column_strategy, (Fraction(1, 3),) * 3)
        self.assertEqual(equilibrium.value, 0)
        self.assertEqual(equilibrium.exploitability, 0)
        self.assertFalse(equilibrium.non_unique)

    def test_zero_sum_solver_reports_non_unique_equilibrium(self) -> None:
        equilibrium = solve_zero_sum([[0, 0], [0, 0]])
        self.assertTrue(equilibrium.non_unique)
        self.assertGreater(len(equilibrium.alternative_supports), 0)

    def test_approximate_zero_sum_solver_converges_near_rock_paper_scissors(self) -> None:
        equilibrium = solve_zero_sum_approximate(
            [[0, -1, 1], [1, 0, -1], [-1, 1, 0]],
            epsilon=0.02,
            max_iterations=40_000,
        )
        self.assertTrue(equilibrium.converged)
        for weight in equilibrium.row_strategy + equilibrium.column_strategy:
            self.assertAlmostEqual(weight, 1 / 3, delta=0.03)
        self.assertAlmostEqual(equilibrium.value, 0.0, delta=0.02)
        self.assertLessEqual(equilibrium.exploitability, 0.02)

    def test_approximate_zero_sum_solver_converges_to_pure_saddle(self) -> None:
        equilibrium = solve_zero_sum_approximate(
            [[2, 1], [3, 0]],
            epsilon=1e-3,
            max_iterations=25_000,
        )
        self.assertTrue(equilibrium.converged)
        self.assertGreater(equilibrium.row_strategy[0], 0.99)
        self.assertGreater(equilibrium.column_strategy[1], 0.99)
        self.assertAlmostEqual(equilibrium.value_lower, 1.0, delta=1e-3)
        self.assertAlmostEqual(equilibrium.value_upper, 1.0, delta=1e-3)

    def test_approximate_zero_sum_solver_supports_rectangular_games(self) -> None:
        equilibrium = solve_zero_sum_approximate(
            [[0, 1, -1], [1, -1, 0]],
            epsilon=0.03,
            max_iterations=30_000,
        )
        self.assertEqual(len(equilibrium.row_strategy), 2)
        self.assertEqual(len(equilibrium.column_strategy), 3)
        self.assertAlmostEqual(sum(equilibrium.row_strategy), 1.0, places=9)
        self.assertAlmostEqual(sum(equilibrium.column_strategy), 1.0, places=9)
        self.assertLessEqual(equilibrium.exploitability, 0.03)

    def test_approximate_zero_sum_solver_is_deterministic(self) -> None:
        left = solve_zero_sum_approximate([[1, -1], [-1, 1]], epsilon=0.01, max_iterations=10_000)
        right = solve_zero_sum_approximate([[1, -1], [-1, 1]], epsilon=0.01, max_iterations=10_000)
        self.assertEqual(left, right)

    def test_approximate_zero_sum_solver_reports_non_convergence_truthfully(self) -> None:
        equilibrium = solve_zero_sum_approximate(
            [[2, 1], [3, 0]],
            epsilon=1e-9,
            max_iterations=5,
        )
        self.assertFalse(equilibrium.converged)
        self.assertEqual(equilibrium.iterations, 5)
        self.assertGreater(equilibrium.exploitability, 1e-9)

    def test_hybrid_solver_keeps_exact_shape_for_large_active_sets(self) -> None:
        equilibrium = solve_zero_sum_hybrid(
            [[0, -1, 1], [1, 0, -1], [-1, 1, 0]],
            exact_support_limit=2,
            epsilon=0.02,
            max_iterations=40_000,
        )
        self.assertTrue(all(isinstance(weight, Fraction) for weight in equilibrium.row_strategy))
        self.assertTrue(all(isinstance(weight, Fraction) for weight in equilibrium.column_strategy))
        self.assertAlmostEqual(float(sum(equilibrium.row_strategy)), 1.0, places=9)
        self.assertAlmostEqual(float(sum(equilibrium.column_strategy)), 1.0, places=9)
        self.assertLessEqual(float(equilibrium.exploitability), 0.03)
