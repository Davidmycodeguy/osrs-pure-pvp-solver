"""Exact and statistical evaluation primitives: ``DamageDistribution`` PMFs, the exact first-strike win
probability, seeded Monte Carlo with Wilson intervals, and exact, approximate (regret matching) and hybrid
zero-sum equilibrium solvers.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations


@dataclass(frozen=True)
class DamageDistribution:
    """A normalised exact probability mass function indexed by damage."""

    probability: Mapping[int, Fraction]

    def __post_init__(self) -> None:
        if not self.probability or any(damage < 0 or chance < 0 for damage, chance in self.probability.items()):
            raise ValueError("Damage distribution must contain non-negative damage and probability")
        if sum(self.probability.values(), Fraction(0)) != 1:
            raise ValueError("Damage distribution must sum exactly to one")

    @classmethod
    def from_success_chance(
        cls, hit_chance: Fraction, max_hit: int, player_zero_becomes_one: bool
    ) -> DamageDistribution:
        if not 0 <= hit_chance <= 1 or max_hit < 0:
            raise ValueError("Invalid hit chance or maximum hit")
        probability: dict[int, Fraction] = {0: 1 - hit_chance}
        if max_hit == 0:
            return cls(probability)
        each = hit_chance / (max_hit + 1)
        for damage in range(max_hit + 1):
            resolved = 1 if player_zero_becomes_one and damage == 0 else damage
            probability[resolved] = probability.get(resolved, Fraction(0)) + each
        return cls({damage: chance for damage, chance in probability.items() if chance})

    @property
    def expected_damage(self) -> Fraction:
        return sum((damage * chance for damage, chance in self.probability.items()), Fraction(0))


@dataclass(frozen=True)
class ExactOutcome:
    win: Fraction
    loss: Fraction
    draw: Fraction


def exact_first_strike_win_probability(
    attacker_hp: int, defender_hp: int, distribution: DamageDistribution
) -> ExactOutcome:
    """Exact repeated-attack evaluator for a declared first-strike micro-model.

    It is intentionally not labelled a complete OSRS duel evaluator: callers
    must provide a separately verified scheduling model before promoting this
    primitive to production PvP use.
    """
    if attacker_hp <= 0 and defender_hp <= 0:
        return ExactOutcome(Fraction(0), Fraction(0), Fraction(1))
    if attacker_hp <= 0:
        return ExactOutcome(Fraction(0), Fraction(1), Fraction(0))
    if defender_hp <= 0:
        return ExactOutcome(Fraction(1), Fraction(0), Fraction(0))
    zero = distribution.probability.get(0, Fraction(0))
    if zero == 1:
        return ExactOutcome(Fraction(0), Fraction(0), Fraction(1))
    # Every non-zero branch decreases defender HP.  Condition on progress to
    # eliminate the otherwise infinite self-loop induced by zero damage.
    normaliser = 1 - zero
    win = Fraction(0)
    for damage, chance in distribution.probability.items():
        if damage <= 0:
            continue
        if damage >= defender_hp:
            win += chance / normaliser
        else:
            continuation = exact_first_strike_win_probability(attacker_hp, defender_hp - damage, distribution)
            win += chance / normaliser * continuation.win
    return ExactOutcome(win, 1 - win, Fraction(0))


@dataclass(frozen=True)
class MatchupResult:
    wins: int
    losses: int
    draws: int
    samples: int
    win_probability: float
    loss_probability: float
    draw_probability: float
    standard_error: float
    confidence_interval_95: tuple[float, float]
    seed: int

    @property
    def trials(self) -> int:
        """Compatibility name for the number of simulated fights."""
        return self.samples


def derived_seed(root_seed: int, *parts: str) -> int:
    payload = f"{root_seed}|{'|'.join(parts)}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def wilson_interval(successes: int, samples: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if samples <= 0:
        raise ValueError("Wilson interval needs positive sample count")
    proportion = successes / samples
    denominator = 1 + z * z / samples
    centre = (proportion + z * z / (2 * samples)) / denominator
    margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * samples)) / samples) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def monte_carlo(
    fight: Callable[[random.Random], str],
    samples: int,
    seed: int,
) -> MatchupResult:
    if samples <= 0:
        raise ValueError("Monte Carlo sample count must be positive")
    rng = random.Random(seed)
    outcomes = {"win": 0, "loss": 0, "draw": 0}
    for _ in range(samples):
        outcome = fight(rng)
        if outcome not in outcomes:
            raise ValueError("Fight callback must return win, loss, or draw")
        outcomes[outcome] += 1
    p = outcomes["win"] / samples
    return MatchupResult(
        wins=outcomes["win"],
        losses=outcomes["loss"],
        draws=outcomes["draw"],
        samples=samples,
        win_probability=p,
        loss_probability=outcomes["loss"] / samples,
        draw_probability=outcomes["draw"] / samples,
        standard_error=math.sqrt(p * (1 - p) / samples),
        confidence_interval_95=wilson_interval(outcomes["win"], samples),
        seed=seed,
    )


@dataclass(frozen=True)
class NashEquilibrium:
    row_strategy: tuple[Fraction, ...]
    column_strategy: tuple[Fraction, ...]
    value: Fraction
    exploitability: Fraction
    non_unique: bool = False
    alternative_supports: tuple[tuple[tuple[Fraction, ...], tuple[Fraction, ...]], ...] = ()


@dataclass(frozen=True)
class ApproximateNashEquilibrium:
    row_strategy: tuple[float, ...]
    column_strategy: tuple[float, ...]
    value_lower: float
    value_upper: float
    exploitability: float
    iterations: int
    converged: bool

    @property
    def value(self) -> float:
        return (self.value_lower + self.value_upper) / 2.0


def _solve_linear(matrix: Sequence[Sequence[Fraction]], vector: Sequence[Fraction]) -> tuple[Fraction, ...] | None:
    size = len(vector)
    if len(matrix) != size or any(len(row) != size for row in matrix):
        return None
    augmented = [list(row) + [vector[index]] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = next((row for row in range(column, size) if augmented[row][column] != 0), None)
        if pivot is None:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        factor = augmented[column][column]
        augmented[column] = [value / factor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                value - factor * pivot_value for value, pivot_value in zip(augmented[row], augmented[column])
            ]
    return tuple(augmented[row][-1] for row in range(size))


def _support_strategy(
    payoff: Sequence[Sequence[Fraction]], rows: tuple[int, ...], columns: tuple[int, ...], *, row_player: bool
) -> tuple[tuple[Fraction, ...], Fraction] | None:
    # Solve B*w - v*1 = 0, sum(w) = 1. For the column player B=A[S,T];
    # for the row player it is B=A[S,T]^T.
    size = len(rows)
    matrix: list[list[Fraction]] = []
    rhs: list[Fraction] = []
    for i in range(size):
        coefficient = [
            payoff[rows[i]][columns[j]] if not row_player else payoff[rows[j]][columns[i]] for j in range(size)
        ]
        matrix.append(coefficient + [Fraction(-1)])
        rhs.append(Fraction(0))
    matrix.append([Fraction(1)] * size + [Fraction(0)])
    rhs.append(Fraction(1))
    solved = _solve_linear(matrix, rhs)
    if solved is None or any(weight < 0 for weight in solved[:-1]):
        return None
    return solved[:-1], solved[-1]


def solve_zero_sum(matrix: Sequence[Sequence[int | Fraction]]) -> NashEquilibrium:
    """Find an exact finite zero-sum equilibrium by equal-size support enumeration.

    This is deliberately dependency-free and suitable for the solver's
    dominance-pruned frontier. Larger matrices should be reduced first.
    """
    payoff = tuple(tuple(Fraction(value) for value in row) for row in matrix)
    n_rows = len(payoff)
    n_columns = len(payoff[0]) if payoff else 0
    if not n_rows or not n_columns or any(len(row) != n_columns for row in payoff):
        raise ValueError("Payoff matrix must be non-empty and rectangular")
    candidates: list[NashEquilibrium] = []
    seen: set[tuple[tuple[Fraction, ...], tuple[Fraction, ...]]] = set()
    for support_size in range(1, min(n_rows, n_columns) + 1):
        for rows in combinations(range(n_rows), support_size):
            for columns in combinations(range(n_columns), support_size):
                column_solution = _support_strategy(payoff, rows, columns, row_player=False)
                row_solution = _support_strategy(payoff, rows, columns, row_player=True)
                if column_solution is None or row_solution is None:
                    continue
                column_weights, column_value = column_solution
                row_weights, row_value = row_solution
                if column_value != row_value:
                    continue
                full_row = tuple(
                    row_weights[rows.index(index)] if index in rows else Fraction(0) for index in range(n_rows)
                )
                full_column = tuple(
                    column_weights[columns.index(index)] if index in columns else Fraction(0)
                    for index in range(n_columns)
                )
                row_payoffs = [
                    sum((payoff[row][column] * full_column[column] for column in range(n_columns)), Fraction(0))
                    for row in range(n_rows)
                ]
                column_payoffs = [
                    sum((full_row[row] * payoff[row][column] for row in range(n_rows)), Fraction(0))
                    for column in range(n_columns)
                ]
                value = row_value
                if all(entry <= value for entry in row_payoffs) and all(entry >= value for entry in column_payoffs):
                    exploitability = max(max(row_payoffs) - value, value - min(column_payoffs))
                    key = (full_row, full_column)
                    if key not in seen:
                        seen.add(key)
                        candidates.append(NashEquilibrium(full_row, full_column, value, exploitability))
    if not candidates:
        raise ValueError("No equilibrium found; reduce dominated strategies or use a numerical fallback")
    primary = candidates[0]
    alternatives = tuple((item.row_strategy, item.column_strategy) for item in candidates[1:])
    return NashEquilibrium(
        primary.row_strategy,
        primary.column_strategy,
        primary.value,
        primary.exploitability,
        non_unique=bool(alternatives),
        alternative_supports=alternatives,
    )


def _validate_numeric_matrix(matrix: Sequence[Sequence[int | float | Fraction]]) -> tuple[tuple[float, ...], ...]:
    payoff = tuple(tuple(float(value) for value in row) for row in matrix)
    n_rows = len(payoff)
    n_columns = len(payoff[0]) if payoff else 0
    if not n_rows or not n_columns or any(len(row) != n_columns for row in payoff):
        raise ValueError("Payoff matrix must be non-empty and rectangular")
    if any(not math.isfinite(value) for row in payoff for value in row):
        raise ValueError("Payoff matrix must contain only finite values")
    return payoff


def _regret_strategy(regrets: Sequence[float]) -> tuple[float, ...]:
    positive = [max(value, 0.0) for value in regrets]
    total = sum(positive)
    if total <= 0:
        width = len(regrets)
        return tuple(1.0 / width for _ in regrets)
    return tuple(value / total for value in positive)


def _normalise(weights: Sequence[float]) -> tuple[float, ...]:
    total = sum(weights)
    if total <= 0:
        width = len(weights)
        return tuple(1.0 / width for _ in weights)
    return tuple(value / total for value in weights)


def solve_zero_sum_approximate(
    matrix: Sequence[Sequence[int | float | Fraction]],
    *,
    epsilon: float = 1e-3,
    max_iterations: int = 50_000,
) -> ApproximateNashEquilibrium:
    """Solve a finite zero-sum game numerically with deterministic regret matching."""
    if epsilon < 0:
        raise ValueError("epsilon must be non-negative")
    if max_iterations < 1:
        raise ValueError("max_iterations must be positive")
    payoff = _validate_numeric_matrix(matrix)
    n_rows = len(payoff)
    n_columns = len(payoff[0])
    row_regrets = [0.0] * n_rows
    column_regrets = [0.0] * n_columns
    row_strategy = [1.0 / n_rows] * n_rows
    column_strategy = [1.0 / n_columns] * n_columns
    row_sum = [0.0] * n_rows
    column_sum = [0.0] * n_columns
    last_result: ApproximateNashEquilibrium | None = None

    for iteration in range(1, max_iterations + 1):
        for index, weight in enumerate(row_strategy):
            row_sum[index] += weight
        for index, weight in enumerate(column_strategy):
            column_sum[index] += weight

        average_row = _normalise(row_sum)
        average_column = _normalise(column_sum)
        row_payoffs = [
            sum(payoff[row][column] * average_column[column] for column in range(n_columns)) for row in range(n_rows)
        ]
        column_payoffs = [
            sum(average_row[row] * payoff[row][column] for row in range(n_rows)) for column in range(n_columns)
        ]
        value_upper = max(row_payoffs)
        value_lower = min(column_payoffs)
        exploitability = value_upper - value_lower
        last_result = ApproximateNashEquilibrium(
            row_strategy=average_row,
            column_strategy=average_column,
            value_lower=value_lower,
            value_upper=value_upper,
            exploitability=exploitability,
            iterations=iteration,
            converged=exploitability <= epsilon,
        )
        if last_result.converged:
            return last_result

        expected_value = sum(
            row_strategy[row] * sum(payoff[row][column] * column_strategy[column] for column in range(n_columns))
            for row in range(n_rows)
        )
        current_row_payoffs = [
            sum(payoff[row][column] * column_strategy[column] for column in range(n_columns)) for row in range(n_rows)
        ]
        current_column_payoffs = [
            sum(row_strategy[row] * payoff[row][column] for row in range(n_rows)) for column in range(n_columns)
        ]
        for row in range(n_rows):
            row_regrets[row] += current_row_payoffs[row] - expected_value
        for column in range(n_columns):
            column_regrets[column] += expected_value - current_column_payoffs[column]
        row_strategy = list(_regret_strategy(row_regrets))
        column_strategy = list(_regret_strategy(column_regrets))

    if last_result is None:
        raise ValueError("Approximate solver did not run any iterations")
    return last_result


def _normalise_fraction_weights(weights: Sequence[Fraction]) -> tuple[Fraction, ...]:
    total = sum(weights, Fraction(0))
    if total <= 0:
        width = len(weights)
        return tuple(Fraction(1, width) for _ in weights)
    return tuple(weight / total for weight in weights)


def _fractionise_weights(weights: Sequence[float], denominator_limit: int) -> tuple[Fraction, ...]:
    return _normalise_fraction_weights(
        tuple(Fraction(str(round(weight, 12))).limit_denominator(denominator_limit) for weight in weights)
    )


def _exploitability_bounds(
    payoff: Sequence[Sequence[Fraction]],
    row_strategy: Sequence[Fraction],
    column_strategy: Sequence[Fraction],
) -> tuple[Fraction, Fraction, Fraction]:
    row_payoffs = [
        sum((payoff[row][column] * column_strategy[column] for column in range(len(column_strategy))), Fraction(0))
        for row in range(len(row_strategy))
    ]
    column_payoffs = [
        sum((row_strategy[row] * payoff[row][column] for row in range(len(row_strategy))), Fraction(0))
        for column in range(len(column_strategy))
    ]
    upper = max(row_payoffs)
    lower = min(column_payoffs)
    return lower, upper, upper - lower


def solve_zero_sum_hybrid(
    matrix: Sequence[Sequence[int | float | Fraction]],
    *,
    exact_support_limit: int = 8,
    epsilon: float = 1e-3,
    max_iterations: int = 50_000,
    denominator_limit: int = 1_000_000,
) -> NashEquilibrium:
    """Return the legacy Fraction equilibrium shape, scaling numerically when needed."""
    payoff = tuple(tuple(Fraction(value) for value in row) for row in matrix)
    n_rows = len(payoff)
    n_columns = len(payoff[0]) if payoff else 0
    if not n_rows or not n_columns or any(len(row) != n_columns for row in payoff):
        raise ValueError("Payoff matrix must be non-empty and rectangular")
    # Support enumeration grows combinatorially in both axes.  A narrow but
    # very tall matrix is not necessarily cheap, so require the entire active
    # game to fit the exact threshold before using it.
    if max(n_rows, n_columns) <= exact_support_limit:
        return solve_zero_sum(payoff)
    approximate = solve_zero_sum_approximate(
        matrix,
        epsilon=epsilon,
        max_iterations=max_iterations,
    )
    row_strategy = _fractionise_weights(approximate.row_strategy, denominator_limit)
    column_strategy = _fractionise_weights(approximate.column_strategy, denominator_limit)
    lower, upper, exploitability = _exploitability_bounds(payoff, row_strategy, column_strategy)
    return NashEquilibrium(
        row_strategy=row_strategy,
        column_strategy=column_strategy,
        value=(lower + upper) / 2,
        exploitability=exploitability,
    )
