import unittest
from fractions import Fraction

from pure_solver.evaluation import MatchupResult, NashEquilibrium
from pure_solver.reporting import (
    PairwiseMatchupReport,
    build_counter_summaries,
    build_nash_summary,
    build_pareto_frontier,
    build_strategy_rankings,
    merge_resource_summaries,
)
from pure_solver.usage import ResourceUsageSummary


def _summary(fights: int, histogram: dict[int, int], *, all_food: int) -> ResourceUsageSummary:
    mean = sum(uses * count for uses, count in histogram.items()) / fights
    return ResourceUsageSummary(
        fights=fights,
        usage_histogram_by_item={"anchovy_pizza": histogram},
        mean_actions_used_by_item={"anchovy_pizza": mean},
        maximum_observed_actions_by_item={"anchovy_pizza": max(histogram)},
        maximum_possible_actions_by_item={"anchovy_pizza": 2},
        reached_maximum_fights_by_item={"anchovy_pizza": histogram.get(2, 0)},
        reached_maximum_rate_by_item={"anchovy_pizza": histogram.get(2, 0) / fights},
        fights_with_food=fights,
        all_food_consumed_fights=all_food,
        all_food_consumed_rate=all_food / fights,
    )


def _matchup(row: str, column: str, win: float, loss: float) -> PairwiseMatchupReport:
    samples = 10
    wins = round(win * samples)
    losses = round(loss * samples)
    draws = samples - wins - losses
    return PairwiseMatchupReport(
        row_strategy_id=row,
        column_strategy_id=column,
        result=MatchupResult(
            wins=wins,
            losses=losses,
            draws=draws,
            samples=samples,
            win_probability=wins / samples,
            loss_probability=losses / samples,
            draw_probability=draws / samples,
            standard_error=0.1,
            confidence_interval_95=(0.1, 0.9),
            seed=1,
        ),
    )


class ReportingTests(unittest.TestCase):
    def test_merge_resource_summaries_preserves_weighted_histograms(self) -> None:
        merged = merge_resource_summaries(
            (
                _summary(10, {0: 4, 1: 3, 2: 3}, all_food=3),
                _summary(20, {0: 5, 1: 10, 2: 5}, all_food=5),
            )
        )
        self.assertEqual(merged.fights, 30)
        self.assertEqual(merged.usage_histogram_by_item["anchovy_pizza"], {0: 9, 1: 13, 2: 8})
        self.assertAlmostEqual(merged.mean_actions_used_by_item["anchovy_pizza"], 29 / 30)
        self.assertEqual(merged.reached_maximum_fights_by_item["anchovy_pizza"], 8)
        self.assertAlmostEqual(merged.all_food_consumed_rate, 8 / 30)

    def test_rankings_frontier_and_nash_reports_are_stable(self) -> None:
        strategy_ids = ("alpha", "beta", "gamma")
        rows = (
            (
                _matchup("alpha", "alpha", 0.5, 0.5),
                _matchup("alpha", "beta", 0.8, 0.2),
                _matchup("alpha", "gamma", 0.6, 0.4),
            ),
            (
                _matchup("beta", "alpha", 0.2, 0.8),
                _matchup("beta", "beta", 0.5, 0.5),
                _matchup("beta", "gamma", 0.4, 0.6),
            ),
            (
                _matchup("gamma", "alpha", 0.4, 0.6),
                _matchup("gamma", "beta", 0.6, 0.4),
                _matchup("gamma", "gamma", 0.5, 0.5),
            ),
        )
        counters = build_counter_summaries(strategy_ids, rows)
        counter_map = {counter.strategy_id: counter for counter in counters}
        rankings = build_strategy_rankings(
            strategy_ids,
            rows,
            counter_map,
            {"alpha": Fraction(1), "beta": Fraction(0), "gamma": Fraction(0)},
        )
        self.assertEqual(rankings[0].strategy_id, "alpha")
        self.assertEqual(rankings[-1].strategy_id, "beta")
        frontier = build_pareto_frontier(rankings)
        self.assertEqual(frontier, (rankings[0],))

        nash = build_nash_summary(
            strategy_ids,
            NashEquilibrium(
                row_strategy=(Fraction(1), Fraction(0), Fraction(0)),
                column_strategy=(Fraction(1), Fraction(0), Fraction(0)),
                value=Fraction(0),
                exploitability=Fraction(0),
            ),
        )
        self.assertEqual(nash.row_strategy["alpha"], 1)
        self.assertEqual(nash.column_strategy["beta"], 0)
        self.assertFalse(nash.non_unique)
        self.assertEqual(nash.to_document()["row_strategy"]["alpha"], {"numerator": 1, "denominator": 1})
