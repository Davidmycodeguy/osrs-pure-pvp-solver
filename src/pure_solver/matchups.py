"""Monte Carlo matchup evaluation on top of the duel simulator: resource-tracking matchups, adaptive
sample schedules, paired common-random-number comparisons, and the full pairwise matchup matrix.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .duel import DuelPolicy, DuelSimulator, DuelState
from .evaluation import MatchupResult, wilson_interval
from .events import TerminalStatus
from .usage import ResourceUsageSummary, measure_fight_usage, summarise_resource_usage

StateFactory = Callable[[], DuelState]


def _outcome(status: TerminalStatus) -> str:
    if status is TerminalStatus.PLAYER_WIN:
        return "win"
    if status is TerminalStatus.OPPONENT_WIN:
        return "loss"
    if status in {TerminalStatus.DRAW, TerminalStatus.TIMEOUT}:
        return "draw"
    raise ValueError("Duel did not reach a terminal outcome")


@dataclass(frozen=True)
class ResourceMatchupResult:
    matchup: MatchupResult
    player_resources: ResourceUsageSummary
    opponent_resources: ResourceUsageSummary


def simulate_matchup_with_resources(
    simulator: DuelSimulator,
    state_factory: StateFactory,
    player_policy: DuelPolicy,
    opponent_policy: DuelPolicy,
    *,
    samples: int,
    seed: int,
) -> ResourceMatchupResult:
    if samples <= 0:
        raise ValueError("Resource matchup needs positive samples")
    stream = random.Random(seed)
    outcomes = {"win": 0, "loss": 0, "draw": 0}
    player_usage = []
    opponent_usage = []
    for _ in range(samples):
        initial = state_factory()
        result = simulator.run(initial, player_policy, opponent_policy, seed=stream.getrandbits(64))
        outcomes[_outcome(result.terminal_status)] += 1
        player_usage.append(
            measure_fight_usage(
                initial.player.inventory,
                result.player.inventory,
                result.player.consumed_items,
                simulator.consumables,
            )
        )
        opponent_usage.append(
            measure_fight_usage(
                initial.opponent.inventory,
                result.opponent.inventory,
                result.opponent.consumed_items,
                simulator.consumables,
            )
        )
    win_probability = outcomes["win"] / samples
    matchup = MatchupResult(
        wins=outcomes["win"],
        losses=outcomes["loss"],
        draws=outcomes["draw"],
        samples=samples,
        win_probability=win_probability,
        loss_probability=outcomes["loss"] / samples,
        draw_probability=outcomes["draw"] / samples,
        standard_error=math.sqrt(win_probability * (1 - win_probability) / samples),
        confidence_interval_95=wilson_interval(outcomes["win"], samples),
        seed=seed,
    )
    return ResourceMatchupResult(
        matchup,
        summarise_resource_usage(player_usage),
        summarise_resource_usage(opponent_usage),
    )


@dataclass(frozen=True)
class AdaptiveMatchup:
    final: MatchupResult
    stages: tuple[MatchupResult, ...]
    ordering_resolved: bool


def adaptive_matchup(
    evaluator: Callable[[int, int], MatchupResult],
    *,
    sample_schedule: Sequence[int] = (10_000, 50_000, 250_000),
    seed: int,
    comparison_probability: float = 0.5,
) -> AdaptiveMatchup:
    if not sample_schedule or any(count <= 0 for count in sample_schedule):
        raise ValueError("Adaptive sample schedule must contain positive counts")
    stages: list[MatchupResult] = []
    resolved = False
    for samples in sample_schedule:
        result = evaluator(samples, seed)
        stages.append(result)
        lower, upper = result.confidence_interval_95
        if upper < comparison_probability or lower > comparison_probability:
            resolved = True
            break
    return AdaptiveMatchup(stages[-1], tuple(stages), resolved)


@dataclass(frozen=True)
class PairedComparison:
    samples: int
    mean_payoff_difference: float
    standard_error: float
    confidence_interval_95: tuple[float, float]
    seed: int


def paired_common_random_comparison(
    candidate_a: Callable[[int], float],
    candidate_b: Callable[[int], float],
    *,
    samples: int,
    seed: int,
) -> PairedComparison:
    """Compare candidates on exactly the same per-fight seed stream."""
    if samples <= 0:
        raise ValueError("Paired comparison needs positive samples")
    stream = random.Random(seed)
    differences: list[float] = []
    for _ in range(samples):
        fight_seed = stream.getrandbits(64)
        differences.append(float(candidate_a(fight_seed)) - float(candidate_b(fight_seed)))
    mean = sum(differences) / samples
    if samples == 1:
        standard_error = 0.0
    else:
        sample_variance = sum((difference - mean) ** 2 for difference in differences) / (samples - 1)
        standard_error = math.sqrt(sample_variance / samples)
    margin = 1.959963984540054 * standard_error
    return PairedComparison(samples, mean, standard_error, (mean - margin, mean + margin), seed)


@dataclass(frozen=True)
class MatchupCell:
    win: float
    loss: float
    draw: float

    @property
    def zero_sum_payoff(self) -> float:
        return self.win - self.loss


@dataclass(frozen=True)
class MatchupMatrix:
    strategy_ids: tuple[str, ...]
    cells: tuple[tuple[MatchupCell, ...], ...]

    @property
    def payoff(self) -> tuple[tuple[float, ...], ...]:
        return tuple(tuple(cell.zero_sum_payoff for cell in row) for row in self.cells)


def build_matchup_matrix(
    strategy_ids: Sequence[str],
    evaluator: Callable[[str, str], MatchupResult],
) -> MatchupMatrix:
    identifiers = tuple(strategy_ids)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Matchup strategy IDs must be unique")
    rows: list[tuple[MatchupCell, ...]] = []
    for row_id in identifiers:
        row: list[MatchupCell] = []
        for column_id in identifiers:
            result = evaluator(row_id, column_id)
            row.append(MatchupCell(result.win_probability, result.loss_probability, result.draw_probability))
        rows.append(tuple(row))
    return MatchupMatrix(identifiers, tuple(rows))
