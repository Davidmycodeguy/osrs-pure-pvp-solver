import unittest
from fractions import Fraction

from pure_solver.double_oracle import (
    OracleScreenEntry,
    OracleScreening,
    solve_double_oracle,
)


class _CountingPayoff:
    def __init__(self, matrix):
        self.matrix = matrix
        self.calls = []

    def __call__(self, row, column):
        self.calls.append((row, column))
        return self.matrix[(row, column)]


class DoubleOracleTests(unittest.TestCase):
    def test_rps_delayed_discovery_reaches_full_cycle(self) -> None:
        candidates = ("R", "P", "S")
        matrix = {
            ("R", "R"): 0,
            ("R", "P"): -1,
            ("R", "S"): 1,
            ("P", "R"): 1,
            ("P", "P"): 0,
            ("P", "S"): -1,
            ("S", "R"): -1,
            ("S", "P"): 1,
            ("S", "S"): 0,
        }
        payoff = _CountingPayoff(matrix)
        result = solve_double_oracle(
            candidates,
            payoff,
            initial_active_rows=("R",),
            initial_active_columns=("S",),
        )
        self.assertEqual(result.status, "exhaustive_convergence")
        self.assertEqual(result.active_rows, candidates)
        self.assertEqual(result.active_columns, candidates)
        self.assertEqual(result.row_support, candidates)
        self.assertEqual(result.column_support, candidates)
        self.assertEqual(result.value, 0)

    def test_pure_dominant_strategy_is_found(self) -> None:
        candidates = ("alpha", "beta", "gamma")
        matrix = {
            ("alpha", "alpha"): 1,
            ("alpha", "beta"): 1,
            ("alpha", "gamma"): 1,
            ("beta", "alpha"): -1,
            ("beta", "beta"): 0,
            ("beta", "gamma"): 0,
            ("gamma", "alpha"): -1,
            ("gamma", "beta"): 0,
            ("gamma", "gamma"): 0,
        }
        result = solve_double_oracle(candidates, _CountingPayoff(matrix), initial_active=("beta",))
        self.assertEqual(result.active_rows, candidates[:2])
        self.assertEqual(result.active_columns, candidates[:2])
        self.assertEqual(result.row_support, ("alpha",))
        self.assertEqual(result.column_support, ("alpha",))
        self.assertEqual(result.value, 1)

    def test_bound_filter_avoids_extra_payoff_calls(self) -> None:
        candidates = ("anchor", "filtered_b", "filtered_c")
        matrix = {(row, column): 0 for row in candidates for column in candidates}
        payoff = _CountingPayoff(matrix)

        def screen(request):
            bound = Fraction(0)
            entries = []
            for candidate_id in request.inactive_candidates:
                if request.side == "row":
                    entries.append(OracleScreenEntry(candidate_id, row_upper_bound=bound))
                else:
                    entries.append(OracleScreenEntry(candidate_id, column_lower_bound=bound))
            return OracleScreening(tuple(entries), exhaustive=True)

        result = solve_double_oracle(candidates, payoff, initial_active=("anchor",), screen=screen)
        self.assertEqual(result.status, "certified_convergence")
        self.assertEqual(result.directed_solves, 1)
        self.assertEqual(payoff.calls, [("anchor", "anchor")])
        self.assertEqual(result.avoided_directed_solves, 8)

    def test_directionality_and_two_sided_discovery_do_not_assume_antisymmetry(self) -> None:
        candidates = ("a", "b", "c")
        matrix = {
            ("a", "a"): 0,
            ("a", "b"): 0,
            ("a", "c"): -2,
            ("b", "a"): 2,
            ("b", "b"): 0,
            ("b", "c"): 0,
            ("c", "a"): 0,
            ("c", "b"): 0,
            ("c", "c"): 0,
        }
        result = solve_double_oracle(candidates, _CountingPayoff(matrix), initial_active=("a",))
        self.assertEqual(result.discoveries[0].side, "row")
        self.assertEqual(result.discoveries[0].candidate_id, "b")
        self.assertEqual(result.discoveries[1].side, "column")
        self.assertEqual(result.discoveries[1].candidate_id, "c")
        self.assertEqual(result.active_rows, ("a", "b"))
        self.assertEqual(result.active_columns, ("a", "c"))
        self.assertEqual(result.final_active_count, 3)

    def test_duplicate_candidates_are_not_added_twice(self) -> None:
        candidates = ("a", "b")
        matrix = {
            ("a", "a"): 0,
            ("a", "b"): -1,
            ("b", "a"): 1,
            ("b", "b"): 0,
        }

        def screen(request):
            entries = (
                OracleScreenEntry("b", priority=(1,)),
                OracleScreenEntry("b", priority=(0,)),
            )
            return OracleScreening(entries, exhaustive=False)

        result = solve_double_oracle(candidates, _CountingPayoff(matrix), initial_active=("a",), screen=screen)
        self.assertEqual(result.active_rows.count("b"), 1)
        self.assertEqual(result.active_columns.count("b"), 1)
        self.assertEqual(
            [discovery.candidate_id for discovery in result.discoveries],
            ["b", "b"],
        )

    def test_incomplete_shortlist_reports_provisional_status(self) -> None:
        candidates = ("a", "b", "c")
        matrix = {
            ("a", "a"): 0,
            ("a", "b"): 0,
            ("a", "c"): -1,
            ("b", "a"): 0,
            ("b", "b"): 0,
            ("b", "c"): 0,
            ("c", "a"): 1,
            ("c", "b"): 0,
            ("c", "c"): 0,
        }

        def screen(request):
            return OracleScreening((OracleScreenEntry("b"),), exhaustive=False)

        result = solve_double_oracle(candidates, _CountingPayoff(matrix), initial_active=("a",), screen=screen)
        self.assertEqual(result.status, "provisional_no_counter")
        self.assertEqual(result.active_rows, ("a",))
        self.assertEqual(result.active_columns, ("a",))

    def test_directed_solve_counts_reuse_cached_pairs(self) -> None:
        candidates = ("a", "b")
        matrix = {
            ("a", "a"): 0,
            ("a", "b"): -1,
            ("b", "a"): 1,
            ("b", "b"): 0,
        }
        payoff = _CountingPayoff(matrix)
        result = solve_double_oracle(candidates, payoff, initial_active=("a",))
        self.assertEqual(result.directed_solves, 4)
        self.assertEqual(len(payoff.calls), 4)
        self.assertEqual(result.final_active_matrix_size, 4)
        self.assertEqual(result.avoided_directed_solves, 0)
        document = result.to_document()
        self.assertEqual(document["directed_solves"], 4)
        self.assertEqual(document["final_active_count"], 2)
        self.assertGreater(document["value"]["denominator"], 0)


if __name__ == "__main__":
    unittest.main()
