"""Sparse two-sided double oracle for finite zero-sum games over a candidate universe: grow the row and column
active sets with best responses found among screened outside candidates, and report certified or exhaustive
convergence, a provisional no-counter result, or budget exhaustion.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from .evaluation import NashEquilibrium, solve_zero_sum_hybrid

Side = Literal["row", "column"]
PayoffCallback = Callable[[str, str], int | Fraction]
EquilibriumSolver = Callable[[Sequence[Sequence[int | Fraction]]], NashEquilibrium]


def _as_fraction(value: int | Fraction) -> Fraction:
    return value if isinstance(value, Fraction) else Fraction(value)


def _fraction_document(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


@dataclass(frozen=True)
class OracleScreenEntry:
    candidate_id: str
    priority: tuple[int | Fraction, ...] = ()
    row_upper_bound: Fraction | None = None
    column_lower_bound: Fraction | None = None


@dataclass(frozen=True)
class OracleScreenRequest:
    side: Side
    inactive_candidates: tuple[str, ...]
    active_rows: tuple[str, ...]
    active_columns: tuple[str, ...]
    support_rows: tuple[str, ...]
    support_columns: tuple[str, ...]
    row_strategy: tuple[tuple[str, Fraction], ...]
    column_strategy: tuple[tuple[str, Fraction], ...]
    value: Fraction
    epsilon: Fraction


@dataclass(frozen=True)
class OracleScreening:
    entries: tuple[OracleScreenEntry, ...]
    exhaustive: bool = True


@dataclass(frozen=True)
class OracleSideSearch:
    side: Side
    inactive_candidate_count: int
    screened_candidate_ids: tuple[str, ...]
    shortlist_exhaustive: bool
    support_ids: tuple[str, ...]
    skipped_by_bound_ids: tuple[str, ...]
    exact_evaluated_ids: tuple[str, ...]
    best_response_candidate_id: str | None
    best_response_value: Fraction | None
    improved: bool
    certified_no_counter: bool
    exhaustive_no_counter: bool
    provisional_no_counter: bool
    budget_blocked: bool
    directed_solves_used: int

    def to_document(self) -> dict[str, object]:
        return {
            "side": self.side,
            "inactive_candidate_count": self.inactive_candidate_count,
            "screened_candidate_ids": self.screened_candidate_ids,
            "shortlist_exhaustive": self.shortlist_exhaustive,
            "support_ids": self.support_ids,
            "skipped_by_bound_ids": self.skipped_by_bound_ids,
            "exact_evaluated_ids": self.exact_evaluated_ids,
            "best_response_candidate_id": self.best_response_candidate_id,
            "best_response_value": None
            if self.best_response_value is None
            else _fraction_document(self.best_response_value),
            "improved": self.improved,
            "certified_no_counter": self.certified_no_counter,
            "exhaustive_no_counter": self.exhaustive_no_counter,
            "provisional_no_counter": self.provisional_no_counter,
            "budget_blocked": self.budget_blocked,
            "directed_solves_used": self.directed_solves_used,
        }


@dataclass(frozen=True)
class OracleDiscovery:
    iteration: int
    side: Side
    candidate_id: str
    expected_payoff: Fraction
    improvement_margin: Fraction

    def to_document(self) -> dict[str, object]:
        return {
            "iteration": self.iteration,
            "side": self.side,
            "candidate_id": self.candidate_id,
            "expected_payoff": _fraction_document(self.expected_payoff),
            "improvement_margin": _fraction_document(self.improvement_margin),
        }


@dataclass(frozen=True)
class OracleIteration:
    iteration: int
    active_rows: tuple[str, ...]
    active_columns: tuple[str, ...]
    value: Fraction
    equilibrium_exploitability: Fraction
    row_support: tuple[str, ...]
    column_support: tuple[str, ...]
    row_search: OracleSideSearch
    column_search: OracleSideSearch
    row_addition: str | None
    column_addition: str | None
    directed_solves_after_iteration: int

    def to_document(self) -> dict[str, object]:
        return {
            "iteration": self.iteration,
            "active_rows": self.active_rows,
            "active_columns": self.active_columns,
            "value": _fraction_document(self.value),
            "equilibrium_exploitability": _fraction_document(self.equilibrium_exploitability),
            "row_support": self.row_support,
            "column_support": self.column_support,
            "row_search": self.row_search.to_document(),
            "column_search": self.column_search.to_document(),
            "row_addition": self.row_addition,
            "column_addition": self.column_addition,
            "directed_solves_after_iteration": self.directed_solves_after_iteration,
        }


@dataclass(frozen=True)
class DoubleOracleResult:
    status: Literal[
        "certified_convergence",
        "exhaustive_convergence",
        "provisional_no_counter",
        "budget_exhaustion",
    ]
    value: Fraction
    epsilon: Fraction
    active_equilibrium_exploitability: Fraction
    remaining_exploitability_bound: Fraction | None
    active_rows: tuple[str, ...]
    active_columns: tuple[str, ...]
    row_strategy: tuple[tuple[str, Fraction], ...]
    column_strategy: tuple[tuple[str, Fraction], ...]
    row_support: tuple[str, ...]
    column_support: tuple[str, ...]
    iterations: tuple[OracleIteration, ...]
    discoveries: tuple[OracleDiscovery, ...]
    directed_solves: int
    cache_hits: int
    total_directed_candidates: int
    avoided_directed_solves: int
    final_active_count: int
    final_active_matrix_size: int

    def to_document(self) -> dict[str, object]:
        return {
            "status": self.status,
            "value": _fraction_document(self.value),
            "epsilon": _fraction_document(self.epsilon),
            "active_equilibrium_exploitability": _fraction_document(self.active_equilibrium_exploitability),
            "remaining_exploitability_bound": (
                None
                if self.remaining_exploitability_bound is None
                else _fraction_document(self.remaining_exploitability_bound)
            ),
            "active_rows": self.active_rows,
            "active_columns": self.active_columns,
            "row_strategy": {candidate_id: _fraction_document(weight) for candidate_id, weight in self.row_strategy},
            "column_strategy": {
                candidate_id: _fraction_document(weight) for candidate_id, weight in self.column_strategy
            },
            "row_support": self.row_support,
            "column_support": self.column_support,
            "iterations": tuple(item.to_document() for item in self.iterations),
            "discoveries": tuple(item.to_document() for item in self.discoveries),
            "directed_solves": self.directed_solves,
            "cache_hits": self.cache_hits,
            "total_directed_candidates": self.total_directed_candidates,
            "avoided_directed_solves": self.avoided_directed_solves,
            "final_active_count": self.final_active_count,
            "final_active_matrix_size": self.final_active_matrix_size,
        }


@dataclass
class _CachedPayoffBook:
    callback: PayoffCallback
    values: dict[tuple[str, str], Fraction]
    misses: int = 0
    hits: int = 0

    def get(self, row_id: str, column_id: str) -> Fraction:
        key = (row_id, column_id)
        if key in self.values:
            self.hits += 1
            return self.values[key]
        value = _as_fraction(self.callback(row_id, column_id))
        self.values[key] = value
        self.misses += 1
        return value

    def missing_count(self, pairs: Sequence[tuple[str, str]]) -> int:
        return sum(1 for pair in pairs if pair not in self.values)


def _normalise_universe(candidate_ids: Sequence[str]) -> tuple[tuple[str, ...], dict[str, int]]:
    identifiers = tuple(candidate_ids)
    if not identifiers:
        raise ValueError("Double-oracle search requires at least one candidate")
    positions: dict[str, int] = {}
    for index, candidate_id in enumerate(identifiers):
        if candidate_id in positions:
            raise ValueError(f"Duplicate candidate ID {candidate_id!r} in universe")
        positions[candidate_id] = index
    return identifiers, positions


def _normalise_active_ids(
    positions: dict[str, int],
    provided: Sequence[str],
) -> tuple[str, ...]:
    if not provided:
        raise ValueError("Active sets must not be empty")
    seen: set[str] = set()
    result: list[str] = []
    for candidate_id in provided:
        if candidate_id not in positions:
            raise ValueError(f"Unknown active candidate ID {candidate_id!r}")
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        result.append(candidate_id)
    return tuple(sorted(result, key=lambda candidate_id: positions[candidate_id]))


def _support_ids(
    strategy: tuple[tuple[str, Fraction], ...],
) -> tuple[str, ...]:
    return tuple(candidate_id for candidate_id, weight in strategy if weight > 0)


def _build_active_matrix(
    active_rows: tuple[str, ...],
    active_columns: tuple[str, ...],
    book: _CachedPayoffBook,
) -> tuple[tuple[Fraction, ...], ...]:
    rows: list[tuple[Fraction, ...]] = []
    for row_id in active_rows:
        rows.append(tuple(book.get(row_id, column_id) for column_id in active_columns))
    return tuple(rows)


def _strategy_pairs(
    candidate_ids: tuple[str, ...],
    weights: Sequence[Fraction],
) -> tuple[tuple[str, Fraction], ...]:
    return tuple((candidate_id, Fraction(weight)) for candidate_id, weight in zip(candidate_ids, weights, strict=True))


def _normalise_screening(
    screening: OracleScreening,
    inactive_candidates: tuple[str, ...],
    positions: dict[str, int],
) -> tuple[OracleScreenEntry, ...]:
    inactive_set = set(inactive_candidates)
    seen: set[str] = set()
    retained: list[OracleScreenEntry] = []
    for entry in screening.entries:
        if entry.candidate_id not in inactive_set or entry.candidate_id in seen:
            continue
        seen.add(entry.candidate_id)
        retained.append(entry)
    if screening.exhaustive:
        for candidate_id in inactive_candidates:
            if candidate_id not in seen:
                retained.append(OracleScreenEntry(candidate_id))
    return tuple(
        sorted(
            retained,
            key=lambda entry: (entry.priority, -positions[entry.candidate_id]),
            reverse=True,
        )
    )


def _expected_row_response(
    candidate_id: str,
    support: tuple[tuple[str, Fraction], ...],
    book: _CachedPayoffBook,
) -> Fraction:
    return sum((weight * book.get(candidate_id, column_id) for column_id, weight in support), Fraction(0))


def _expected_column_response(
    candidate_id: str,
    support: tuple[tuple[str, Fraction], ...],
    book: _CachedPayoffBook,
) -> Fraction:
    return sum((weight * book.get(row_id, candidate_id) for row_id, weight in support), Fraction(0))


def _missing_support_pairs(
    side: Side,
    candidate_id: str,
    support_ids: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    if side == "row":
        return tuple((candidate_id, opponent_id) for opponent_id in support_ids)
    return tuple((opponent_id, candidate_id) for opponent_id in support_ids)


def _default_screen(request: OracleScreenRequest) -> OracleScreening:
    return OracleScreening(tuple(OracleScreenEntry(candidate_id) for candidate_id in request.inactive_candidates))


def _search_side(
    *,
    side: Side,
    all_candidates: tuple[str, ...],
    positions: dict[str, int],
    active_rows: tuple[str, ...],
    active_columns: tuple[str, ...],
    row_strategy: tuple[tuple[str, Fraction], ...],
    column_strategy: tuple[tuple[str, Fraction], ...],
    value: Fraction,
    epsilon: Fraction,
    screen: Callable[[OracleScreenRequest], OracleScreening],
    book: _CachedPayoffBook,
    max_payoff_calls: int | None,
) -> OracleSideSearch:
    active_side = active_rows if side == "row" else active_columns
    inactive_candidates = tuple(candidate_id for candidate_id in all_candidates if candidate_id not in active_side)
    support = column_strategy if side == "row" else row_strategy
    support_ids = tuple(candidate_id for candidate_id, weight in support if weight > 0)
    if not inactive_candidates:
        return OracleSideSearch(
            side=side,
            inactive_candidate_count=0,
            screened_candidate_ids=(),
            shortlist_exhaustive=True,
            support_ids=support_ids,
            skipped_by_bound_ids=(),
            exact_evaluated_ids=(),
            best_response_candidate_id=None,
            best_response_value=None,
            improved=False,
            certified_no_counter=True,
            exhaustive_no_counter=True,
            provisional_no_counter=False,
            budget_blocked=False,
            directed_solves_used=0,
        )

    strategy_request = OracleScreenRequest(
        side=side,
        inactive_candidates=inactive_candidates,
        active_rows=active_rows,
        active_columns=active_columns,
        support_rows=_support_ids(row_strategy),
        support_columns=_support_ids(column_strategy),
        row_strategy=row_strategy,
        column_strategy=column_strategy,
        value=value,
        epsilon=epsilon,
    )
    screening = screen(strategy_request)
    if not isinstance(screening, OracleScreening):
        raise TypeError("Screen callback must return OracleScreening")
    entries = _normalise_screening(screening, inactive_candidates, positions)
    lower_threshold = value - epsilon
    upper_threshold = value + epsilon
    exact_evaluated: list[str] = []
    skipped_by_bound: list[str] = []
    best_candidate_id: str | None = None
    best_value: Fraction | None = None
    budget_blocked = False
    calls_before = book.misses

    for entry in entries:
        bound = entry.row_upper_bound if side == "row" else entry.column_lower_bound
        if side == "row":
            if bound is not None and bound <= upper_threshold:
                skipped_by_bound.append(entry.candidate_id)
                continue
            if best_value is not None and bound is not None and bound <= best_value:
                skipped_by_bound.append(entry.candidate_id)
                continue
        else:
            if bound is not None and bound >= lower_threshold:
                skipped_by_bound.append(entry.candidate_id)
                continue
            if best_value is not None and bound is not None and bound >= best_value:
                skipped_by_bound.append(entry.candidate_id)
                continue
        required_pairs = _missing_support_pairs(side, entry.candidate_id, support_ids)
        if max_payoff_calls is not None and book.misses + book.missing_count(required_pairs) > max_payoff_calls:
            budget_blocked = True
            break
        score = (
            _expected_row_response(entry.candidate_id, support, book)
            if side == "row"
            else _expected_column_response(entry.candidate_id, support, book)
        )
        exact_evaluated.append(entry.candidate_id)
        if best_candidate_id is None:
            best_candidate_id = entry.candidate_id
            best_value = score
            continue
        if side == "row":
            if score > best_value or (
                score == best_value and positions[entry.candidate_id] < positions[best_candidate_id]
            ):
                best_candidate_id = entry.candidate_id
                best_value = score
        else:
            if score < best_value or (
                score == best_value and positions[entry.candidate_id] < positions[best_candidate_id]
            ):
                best_candidate_id = entry.candidate_id
                best_value = score

    improved = (
        best_candidate_id is not None
        and best_value is not None
        and (best_value > upper_threshold if side == "row" else best_value < lower_threshold)
    )
    exhaustive_no_counter = (
        screening.exhaustive
        and not budget_blocked
        and not improved
        and len(exact_evaluated) == len(inactive_candidates)
    )
    certified_no_counter = (
        screening.exhaustive
        and not budget_blocked
        and not improved
        and len(exact_evaluated) + len(skipped_by_bound) == len(inactive_candidates)
        and len(skipped_by_bound) > 0
    )
    provisional_no_counter = not improved and not budget_blocked and not (exhaustive_no_counter or certified_no_counter)
    return OracleSideSearch(
        side=side,
        inactive_candidate_count=len(inactive_candidates),
        screened_candidate_ids=tuple(entry.candidate_id for entry in entries),
        shortlist_exhaustive=screening.exhaustive,
        support_ids=support_ids,
        skipped_by_bound_ids=tuple(skipped_by_bound),
        exact_evaluated_ids=tuple(exact_evaluated),
        best_response_candidate_id=best_candidate_id if improved else None,
        best_response_value=best_value if improved else None,
        improved=improved,
        certified_no_counter=certified_no_counter,
        exhaustive_no_counter=exhaustive_no_counter,
        provisional_no_counter=provisional_no_counter,
        budget_blocked=budget_blocked,
        directed_solves_used=book.misses - calls_before,
    )


def solve_double_oracle(
    candidate_ids: Sequence[str],
    payoff: PayoffCallback,
    *,
    initial_active: Sequence[str] | None = None,
    initial_active_rows: Sequence[str] | None = None,
    initial_active_columns: Sequence[str] | None = None,
    epsilon: int | Fraction = 0,
    screen: Callable[[OracleScreenRequest], OracleScreening] | None = None,
    equilibrium_solver: EquilibriumSolver = solve_zero_sum_hybrid,
    max_iterations: int | None = None,
    max_payoff_calls: int | None = None,
) -> DoubleOracleResult:
    all_candidates, positions = _normalise_universe(candidate_ids)
    seed_active = tuple(initial_active or ())
    row_seed = initial_active_rows if initial_active_rows is not None else seed_active
    column_seed = initial_active_columns if initial_active_columns is not None else seed_active
    active_rows = _normalise_active_ids(positions, row_seed)
    active_columns = _normalise_active_ids(positions, column_seed)
    epsilon_fraction = _as_fraction(epsilon)
    screen_callback = screen or _default_screen
    book = _CachedPayoffBook(payoff, {})
    iterations: list[OracleIteration] = []
    discoveries: list[OracleDiscovery] = []
    status: Literal[
        "certified_convergence",
        "exhaustive_convergence",
        "provisional_no_counter",
        "budget_exhaustion",
    ] = "budget_exhaustion"
    final_value = Fraction(0)
    final_equilibrium_exploitability = Fraction(0)
    final_row_strategy: tuple[tuple[str, Fraction], ...] = ()
    final_column_strategy: tuple[tuple[str, Fraction], ...] = ()
    final_row_support: tuple[str, ...] = ()
    final_column_support: tuple[str, ...] = ()

    for iteration_number in range(1, (max_iterations or (len(all_candidates) ** 2 + 1)) + 1):
        iteration_active_rows = active_rows
        iteration_active_columns = active_columns
        matrix = _build_active_matrix(iteration_active_rows, iteration_active_columns, book)
        equilibrium = equilibrium_solver(matrix)
        if len(equilibrium.row_strategy) != len(iteration_active_rows) or len(equilibrium.column_strategy) != len(
            iteration_active_columns
        ):
            raise ValueError("Equilibrium solver returned a strategy with the wrong shape")
        row_strategy = _strategy_pairs(iteration_active_rows, equilibrium.row_strategy)
        column_strategy = _strategy_pairs(iteration_active_columns, equilibrium.column_strategy)
        final_value = equilibrium.value
        final_equilibrium_exploitability = equilibrium.exploitability
        final_row_strategy = row_strategy
        final_column_strategy = column_strategy
        final_row_support = _support_ids(row_strategy)
        final_column_support = _support_ids(column_strategy)

        row_search = _search_side(
            side="row",
            all_candidates=all_candidates,
            positions=positions,
            active_rows=active_rows,
            active_columns=active_columns,
            row_strategy=row_strategy,
            column_strategy=column_strategy,
            value=equilibrium.value,
            epsilon=epsilon_fraction,
            screen=screen_callback,
            book=book,
            max_payoff_calls=max_payoff_calls,
        )
        column_search = _search_side(
            side="column",
            all_candidates=all_candidates,
            positions=positions,
            active_rows=active_rows,
            active_columns=active_columns,
            row_strategy=row_strategy,
            column_strategy=column_strategy,
            value=equilibrium.value,
            epsilon=epsilon_fraction,
            screen=screen_callback,
            book=book,
            max_payoff_calls=max_payoff_calls,
        )

        row_addition = row_search.best_response_candidate_id if row_search.improved else None
        column_addition = column_search.best_response_candidate_id if column_search.improved else None
        if row_addition is not None:
            active_rows = tuple(
                sorted(set(active_rows) | {row_addition}, key=lambda candidate_id: positions[candidate_id])
            )
            discoveries.append(
                OracleDiscovery(
                    iteration=iteration_number,
                    side="row",
                    candidate_id=row_addition,
                    expected_payoff=row_search.best_response_value or Fraction(0),
                    improvement_margin=(row_search.best_response_value or Fraction(0)) - equilibrium.value,
                )
            )
        if column_addition is not None:
            active_columns = tuple(
                sorted(set(active_columns) | {column_addition}, key=lambda candidate_id: positions[candidate_id])
            )
            discoveries.append(
                OracleDiscovery(
                    iteration=iteration_number,
                    side="column",
                    candidate_id=column_addition,
                    expected_payoff=column_search.best_response_value or Fraction(0),
                    improvement_margin=equilibrium.value - (column_search.best_response_value or Fraction(0)),
                )
            )

        iterations.append(
            OracleIteration(
                iteration=iteration_number,
                active_rows=iteration_active_rows,
                active_columns=iteration_active_columns,
                value=equilibrium.value,
                equilibrium_exploitability=equilibrium.exploitability,
                row_support=final_row_support,
                column_support=final_column_support,
                row_search=row_search,
                column_search=column_search,
                row_addition=row_addition,
                column_addition=column_addition,
                directed_solves_after_iteration=book.misses,
            )
        )

        if row_search.budget_blocked or column_search.budget_blocked:
            status = "budget_exhaustion"
            break
        if row_addition is not None or column_addition is not None:
            continue
        if equilibrium.exploitability > epsilon_fraction:
            status = "provisional_no_counter"
        elif row_search.provisional_no_counter or column_search.provisional_no_counter:
            status = "provisional_no_counter"
        elif row_search.exhaustive_no_counter and column_search.exhaustive_no_counter:
            status = "exhaustive_convergence"
        elif row_search.certified_no_counter and column_search.certified_no_counter:
            status = "certified_convergence"
        else:
            status = "provisional_no_counter"
        break
    else:
        status = "budget_exhaustion"

    # A final iteration may discover a response immediately before an explicit
    # iteration budget is exhausted. Re-solve that enlarged active game so the
    # returned mixtures always match the returned active sets.
    if len(final_row_strategy) != len(active_rows) or len(final_column_strategy) != len(active_columns):
        equilibrium = equilibrium_solver(_build_active_matrix(active_rows, active_columns, book))
        final_value = equilibrium.value
        final_equilibrium_exploitability = equilibrium.exploitability
        final_row_strategy = _strategy_pairs(active_rows, equilibrium.row_strategy)
        final_column_strategy = _strategy_pairs(active_columns, equilibrium.column_strategy)
        final_row_support = _support_ids(final_row_strategy)
        final_column_support = _support_ids(final_column_strategy)

    remaining_bound = (
        max(epsilon_fraction, final_equilibrium_exploitability)
        if status in {"certified_convergence", "exhaustive_convergence"}
        else None
    )

    total_directed = len(all_candidates) ** 2
    return DoubleOracleResult(
        status=status,
        value=final_value,
        epsilon=epsilon_fraction,
        active_equilibrium_exploitability=final_equilibrium_exploitability,
        remaining_exploitability_bound=remaining_bound,
        active_rows=active_rows,
        active_columns=active_columns,
        row_strategy=final_row_strategy,
        column_strategy=final_column_strategy,
        row_support=final_row_support,
        column_support=final_column_support,
        iterations=tuple(iterations),
        discoveries=tuple(discoveries),
        directed_solves=book.misses,
        cache_hits=book.hits,
        total_directed_candidates=total_directed,
        avoided_directed_solves=total_directed - book.misses,
        final_active_count=len(set(active_rows) | set(active_columns)),
        final_active_matrix_size=len(active_rows) * len(active_columns),
    )
