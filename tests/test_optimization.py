import unittest

from pure_solver.optimization import enumerate_restricted_policies, optimize_restricted_policy


class PolicyOptimizationTests(unittest.TestCase):
    def test_grid_search_returns_best_policy_and_full_ranking(self) -> None:
        policies = enumerate_restricted_policies(1, 2, eat_thresholds=[4, 6], ko_thresholds=[5, 8])
        best, ranking = optimize_restricted_policy(
            policies,
            lambda policy: 1.0 if (policy.eat_threshold, policy.ko_threshold) == (6, 8) else 0.0,
        )
        self.assertEqual(len(ranking), 4)
        self.assertEqual((best.policy.eat_threshold, best.policy.ko_threshold), (6, 8))
