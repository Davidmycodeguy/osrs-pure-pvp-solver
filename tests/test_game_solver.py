import unittest
from fractions import Fraction

from pure_solver.evaluation import MatchupResult
from pure_solver.game_solver import StrategyCandidate, solve_strategy_space
from pure_solver.matchups import ResourceMatchupResult
from pure_solver.reporting import StrategyDescriptor
from pure_solver.ruleset import load_ruleset
from pure_solver.usage import ResourceUsageSummary


class _VerifiedRuleset:
    reproducibility_metadata = {"ruleset_id": "fixture"}

    def preflight(self) -> None:
        return None


def _resources() -> ResourceUsageSummary:
    return ResourceUsageSummary(
        fights=10,
        usage_histogram_by_item={},
        mean_actions_used_by_item={},
        maximum_observed_actions_by_item={},
        maximum_possible_actions_by_item={},
        reached_maximum_fights_by_item={},
        reached_maximum_rate_by_item={},
        fights_with_food=0,
        all_food_consumed_fights=0,
        all_food_consumed_rate=None,
    )


def _strategy(strategy_id: str) -> StrategyCandidate:
    return StrategyCandidate(
        StrategyDescriptor(
            strategy_id=strategy_id,
            account_id=strategy_id,
            combat_level=40,
            attack_level=40,
            strength_level=40,
            ranged_level=1,
            magic_level=1,
            prayer_level=1,
            hitpoints_level=40,
            primary_weapon={"item_id": 1333},
            ko_weapon={"item_id": 1319},
            ammunition=None,
            inventory_entries=(),
            reserved_switch_slots=1,
            policy={"eat_threshold": 10},
        )
    )


class GameSolverTests(unittest.TestCase):
    def test_real_ruleset_accepts_full_game_after_timing_promotion(self) -> None:
        load_ruleset("rulesets/osrs-f2p-v1").preflight()

    def test_verified_strategy_space_builds_complete_report(self) -> None:
        strategies = (_strategy("a"), _strategy("b"))

        def evaluator(row, column):
            if row.descriptor.strategy_id == column.descriptor.strategy_id:
                wins, losses = 5, 5
            elif row.descriptor.strategy_id == "a":
                wins, losses = 7, 3
            else:
                wins, losses = 3, 7
            result = MatchupResult(
                wins,
                losses,
                0,
                10,
                wins / 10,
                losses / 10,
                0.0,
                0.1,
                (0.0, 1.0),
                1,
            )
            return ResourceMatchupResult(result, _resources(), _resources())

        report = solve_strategy_space(_VerifiedRuleset(), strategies, evaluator)
        self.assertEqual(report.search.strategy_count, 2)
        self.assertEqual(report.search.matchup_count, 4)
        self.assertEqual(len(report.pairwise_matchups), 4)
        self.assertEqual(report.rankings[0].strategy_id, "a")
        self.assertEqual(report.nash.exploitability, Fraction(0))
