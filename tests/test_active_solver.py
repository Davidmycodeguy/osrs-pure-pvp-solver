import unittest
from fractions import Fraction

from pure_solver.accounts import LevelRange
from pure_solver.active_solver import (
    _screen_from_equilibrium_features,
    solve_supported_active_strategy_space,
)
from pure_solver.double_oracle import OracleScreenRequest
from pure_solver.ruleset import load_ruleset

RULESET = load_ruleset("rulesets/osrs-f2p-v1")


class ActiveSolverTests(unittest.TestCase):
    def test_outside_screen_changes_with_current_equilibrium_support(self) -> None:
        features = {
            "offence": (Fraction(1), Fraction(0), Fraction(0), Fraction(0), Fraction(0), Fraction(0)),
            "burst": (Fraction(0), Fraction(1), Fraction(0), Fraction(0), Fraction(0), Fraction(0)),
            "tank": (Fraction(0), Fraction(0), Fraction(0), Fraction(0), Fraction(1), Fraction(0)),
            "food": (Fraction(0), Fraction(0), Fraction(0), Fraction(0), Fraction(0), Fraction(1)),
        }
        screen = _screen_from_equilibrium_features(features, outside_batch_size=1)

        def request(opponent: str) -> OracleScreenRequest:
            return OracleScreenRequest(
                side="row",
                inactive_candidates=("offence", "burst"),
                active_rows=("offence",),
                active_columns=(opponent,),
                support_rows=("offence",),
                support_columns=(opponent,),
                row_strategy=(("offence", Fraction(1)),),
                column_strategy=((opponent, Fraction(1)),),
                value=Fraction(0),
                epsilon=Fraction(0),
            )

        self.assertEqual(screen(request("food")).entries[0].candidate_id, "offence")
        self.assertEqual(screen(request("tank")).entries[0].candidate_id, "burst")

    def test_supported_active_solver_uses_sparse_directional_payoffs(self) -> None:
        report = solve_supported_active_strategy_space(
            RULESET,
            attack_range=LevelRange(40, 40),
            strength_range=LevelRange(40, 40),
            ranged_range=LevelRange(1, 1),
            prayer_range=LevelRange(1, 1),
            hitpoints_range=LevelRange(40, 40),
            combat_minimum=30,
            combat_maximum=40,
            samples=1,
            seed=7,
            maximum_ticks=20,
            maximum_accounts=2,
            candidate_pool_size=2,
            initial_active_size=1,
            outside_batch_size=1,
            oracle_epsilon=Fraction(1, 50),
            oracle_max_iterations=2,
            account_mode="independent_hp",
        )

        verification = report.verification
        self.assertEqual(verification["scope"], "bounded_melee_ranged_pairwise_restricted_grid_double_oracle_v1")
        self.assertEqual(verification["status"], "provisional")
        self.assertFalse(verification["perfect_play_claim"])
        self.assertFalse(verification["magic_complete"])
        self.assertTrue(verification["pairwise_policy_optimization"]["enabled"])
        self.assertEqual(
            verification["pairwise_policy_optimization"]["authority"],
            "restricted_grid_search",
        )
        self.assertEqual(verification["candidate_pool_count"], 2)
        self.assertEqual(verification["initial_active_count"], 1)
        self.assertLessEqual(verification["directed_simulator_solves"], 4)
        self.assertEqual(
            verification["directed_solves_avoided_vs_pool_all_pairs"],
            4 - verification["directed_simulator_solves"],
        )


if __name__ == "__main__":
    unittest.main()
