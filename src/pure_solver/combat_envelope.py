"""Exact raw-burst combat envelopes for one resolved defender state: PMF convolution, fixed-window and fixed-
sequence damage, an adaptive finite-horizon KO dynamic programme, and the normalised metrics that
:mod:`pure_solver.candidate_reduction` consumes.

Incoming damage, eating, prayer changes and movement are deliberately outside this module.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from functools import cache

from .canonical import canonical_hash
from .evaluation import DamageDistribution
from .profiles import AttackProfile


def _sorted_probability(probability: Mapping[int, Fraction]) -> dict[int, Fraction]:
    return dict(
        sorted(
            ((int(damage), Fraction(chance)) for damage, chance in probability.items() if chance),
            key=lambda item: item[0],
        )
    )


def _delta_distribution() -> DamageDistribution:
    return DamageDistribution({0: Fraction(1)})


def _distribution_key(distribution: DamageDistribution) -> tuple[tuple[int, Fraction], ...]:
    return tuple(
        sorted(
            ((int(damage), Fraction(chance)) for damage, chance in distribution.probability.items() if chance),
            key=lambda item: item[0],
        )
    )


def _distribution_from_key(key: tuple[tuple[int, Fraction], ...]) -> DamageDistribution:
    return DamageDistribution(dict(key))


def _ko_probability(distribution: DamageDistribution, hp: int) -> Fraction:
    if hp <= 0:
        return Fraction(1)
    return sum(chance for damage, chance in distribution.probability.items() if damage >= hp)


def _prefer_sequence(candidate: Sequence[str], incumbent: Sequence[str]) -> bool:
    if not incumbent:
        return bool(candidate)
    if not candidate:
        return False
    return tuple(candidate) < tuple(incumbent)


def convolve_distributions(*distributions: DamageDistribution) -> DamageDistribution:
    """Exact convolution of one or more damage PMFs."""
    if not distributions:
        return _delta_distribution()
    probability: dict[int, Fraction] = {0: Fraction(1)}
    for distribution in distributions:
        next_probability: dict[int, Fraction] = {}
        for left_damage, left_chance in probability.items():
            for right_damage, right_chance in distribution.probability.items():
                total = left_damage + right_damage
                next_probability[total] = next_probability.get(total, Fraction(0)) + left_chance * right_chance
        probability = next_probability
    return DamageDistribution(_sorted_probability(probability))


@dataclass(frozen=True)
class AttackOption:
    """One legal repeated attack option for raw burst against a static target."""

    option_id: str
    damage_type: str
    cooldown_ticks: int
    minimum_distance: int
    maximum_distance: int
    impact_delay_by_distance: Mapping[int, int]
    distribution: DamageDistribution
    attack_roll: int | None = None
    defence_roll: int | None = None
    hit_chance: Fraction | None = None
    max_hit: int | None = None

    def __post_init__(self) -> None:
        if not self.option_id:
            raise ValueError("Attack option needs a non-empty option_id")
        if self.cooldown_ticks < 1:
            raise ValueError("Attack option cooldown must be positive")
        if self.minimum_distance < 0 or self.maximum_distance < self.minimum_distance:
            raise ValueError("Attack option has an invalid distance range")
        expected = set(range(self.minimum_distance, self.maximum_distance + 1))
        actual = {int(distance) for distance in self.impact_delay_by_distance}
        if actual != expected:
            raise ValueError("Attack option impact delays must cover every legal distance exactly once")
        if any(int(delay) < 0 for delay in self.impact_delay_by_distance.values()):
            raise ValueError("Attack option impact delays must be non-negative")
        if self.hit_chance is not None and not 0 <= self.hit_chance <= 1:
            raise ValueError("Attack option hit chance must be between zero and one")
        if self.max_hit is not None and self.max_hit < 0:
            raise ValueError("Attack option max hit cannot be negative")

    @classmethod
    def from_attack_profile(cls, option_id: str, profile: AttackProfile) -> AttackOption:
        return cls(
            option_id=option_id,
            damage_type=profile.damage_type,
            cooldown_ticks=profile.timing.cooldown_ticks,
            minimum_distance=profile.timing.minimum_distance,
            maximum_distance=profile.timing.maximum_distance,
            impact_delay_by_distance=dict(profile.timing.impact_delay_by_distance),
            distribution=profile.distribution(),
            attack_roll=profile.attack_roll,
            defence_roll=profile.defence_roll,
            hit_chance=profile.hit_chance,
            max_hit=profile.max_hit,
        )

    def legal_at_distance(self, distance: int) -> bool:
        return self.minimum_distance <= distance <= self.maximum_distance

    def impact_delay(self, distance: int) -> int:
        if not self.legal_at_distance(distance):
            raise ValueError(f"{self.option_id!r} is illegal at distance {distance}")
        return int(self.impact_delay_by_distance[distance])


@dataclass(frozen=True)
class FixedWindowResult:
    tick_window: int
    distance: int
    attack_count: int
    impact_ticks: tuple[int, ...]
    distribution: DamageDistribution

    @property
    def expected_damage(self) -> Fraction:
        return self.distribution.expected_damage

    def ko_probability(self, hp: int) -> Fraction:
        return _ko_probability(self.distribution, hp)


@dataclass(frozen=True)
class FixedSequenceResult:
    tick_window: int
    distance: int
    sequence: tuple[str, ...]
    attack_ticks: tuple[int, ...]
    impact_ticks: tuple[int, ...]
    distribution: DamageDistribution

    @property
    def expected_damage(self) -> Fraction:
        return self.distribution.expected_damage

    def ko_probability(self, hp: int) -> Fraction:
        return _ko_probability(self.distribution, hp)


@dataclass(frozen=True)
class AdaptiveKOResult:
    tick_window: int
    distance: int
    target_hp: int
    ko_probability: Fraction
    first_action: str | None
    equally_optimal_first_actions: tuple[str, ...]


@dataclass(frozen=True)
class StackEnvelopeEntry:
    tick_window: int
    target_hp: int
    best_fixed: FixedSequenceResult
    adaptive: AdaptiveKOResult


@dataclass(frozen=True)
class CombatEnvelope:
    """Exact raw-burst envelope for one resolved defender state.

    The attack options must already contain the OSRS-resolved accuracy and
    damage PMFs for ``defence_state_id``. Incoming attacks, eating, prayer
    changes, movement, and opponent reactions are intentionally outside this
    object and remain the responsibility of the full duel oracle.
    """

    candidate_id: str
    defence_state_id: str
    hitpoints: int
    prayer: int
    distance: int
    options: tuple[AttackOption, ...]
    windows: tuple[int, ...]
    hp_thresholds: tuple[int, ...]
    fixed_windows: tuple[tuple[str, FixedWindowResult], ...]
    stacks: tuple[StackEnvelopeEntry, ...]
    equivalence_signature: str

    @property
    def capabilities(self) -> tuple[str, ...]:
        tokens = {
            *(f"style:{option.damage_type}" for option in self.options),
            *(
                f"range:legal:{value}"
                for option in self.options
                for value in range(option.minimum_distance, option.maximum_distance + 1)
            ),
        }
        if len(self.options) > 1:
            tokens.add("switch:multiple_attack_options")
        return tuple(sorted(tokens))

    @property
    def normalized_metrics(self) -> Mapping[str, Fraction]:
        metrics: dict[str, Fraction] = {
            "hitpoints": Fraction(self.hitpoints),
            "prayer": Fraction(self.prayer),
            "max_range": Fraction(max(option.maximum_distance for option in self.options)),
        }
        for option in self.options:
            metrics[f"sustained:{option.option_id}"] = option.distribution.expected_damage / option.cooldown_ticks
        for option_id, result in self.fixed_windows:
            metrics[f"expected:{option_id}:{result.tick_window}"] = result.expected_damage
        for entry in self.stacks:
            metrics[f"ko:{entry.tick_window}:{entry.target_hp}"] = entry.adaptive.ko_probability
            metrics[f"fixed_stack:{entry.tick_window}:{entry.target_hp}"] = entry.best_fixed.ko_probability(
                entry.target_hp
            )
        return metrics

    def to_document(self) -> Mapping[str, object]:
        def fraction(value: Fraction) -> Mapping[str, int]:
            return {"numerator": value.numerator, "denominator": value.denominator}

        def distribution(value: DamageDistribution) -> Mapping[str, Mapping[str, int]]:
            return {str(damage): fraction(chance) for damage, chance in sorted(value.probability.items())}

        return {
            "candidate_id": self.candidate_id,
            "defence_state_id": self.defence_state_id,
            "hitpoints": self.hitpoints,
            "prayer": self.prayer,
            "distance": self.distance,
            "windows": self.windows,
            "hp_thresholds": self.hp_thresholds,
            "equivalence_signature": self.equivalence_signature,
            "capabilities": self.capabilities,
            "options": tuple(
                {
                    "option_id": option.option_id,
                    "damage_type": option.damage_type,
                    "attack_roll": option.attack_roll,
                    "defence_roll": option.defence_roll,
                    "hit_chance": None if option.hit_chance is None else fraction(option.hit_chance),
                    "max_hit": option.max_hit if option.max_hit is not None else max(option.distribution.probability),
                    "cooldown_ticks": option.cooldown_ticks,
                    "minimum_distance": option.minimum_distance,
                    "maximum_distance": option.maximum_distance,
                    "impact_delay_by_distance": dict(option.impact_delay_by_distance),
                    "expected_damage_per_attack": fraction(option.distribution.expected_damage),
                    "expected_damage_per_tick": fraction(option.distribution.expected_damage / option.cooldown_ticks),
                    "damage_distribution": distribution(option.distribution),
                }
                for option in self.options
            ),
            "fixed_windows": tuple(
                {
                    "option_id": option_id,
                    "tick_window": result.tick_window,
                    "attack_count": result.attack_count,
                    "impact_ticks": result.impact_ticks,
                    "expected_damage": fraction(result.expected_damage),
                    "damage_distribution": distribution(result.distribution),
                }
                for option_id, result in self.fixed_windows
            ),
            "stack_ko": tuple(
                {
                    "tick_window": entry.tick_window,
                    "target_hp": entry.target_hp,
                    "best_fixed_sequence": entry.best_fixed.sequence,
                    "best_fixed_probability": fraction(entry.best_fixed.ko_probability(entry.target_hp)),
                    "adaptive_probability": fraction(entry.adaptive.ko_probability),
                    "adaptive_first_action": entry.adaptive.first_action,
                }
                for entry in self.stacks
            ),
            "scope_note": "raw burst against a non-reactive defender; the full duel oracle remains authoritative",
        }


def fixed_option_window_distribution(
    option: AttackOption,
    *,
    tick_window: int,
    distance: int,
) -> FixedWindowResult:
    """Repeat one option on cooldown and return the exact pre-deadline damage PMF."""
    if tick_window < 1:
        raise ValueError("tick_window must be positive")
    if not option.legal_at_distance(distance):
        raise ValueError(f"{option.option_id!r} is illegal at distance {distance}")
    impact_delay = option.impact_delay(distance)
    hits: list[DamageDistribution] = []
    impact_ticks: list[int] = []
    attack_tick = 0
    while attack_tick < tick_window:
        impact_tick = attack_tick + impact_delay
        if impact_tick < tick_window:
            hits.append(option.distribution)
            impact_ticks.append(impact_tick)
        attack_tick += option.cooldown_ticks
    return FixedWindowResult(
        tick_window=tick_window,
        distance=distance,
        attack_count=len(hits),
        impact_ticks=tuple(impact_ticks),
        distribution=convolve_distributions(*hits),
    )


def fixed_sequence_window_distribution(
    options: Sequence[AttackOption],
    *,
    tick_window: int,
    distance: int,
) -> FixedSequenceResult:
    """Evaluate a fixed legal attack sequence under the shared attack cooldown rule."""
    if tick_window < 1:
        raise ValueError("tick_window must be positive")
    attack_tick = 0
    hits: list[DamageDistribution] = []
    sequence: list[str] = []
    attack_ticks: list[int] = []
    impact_ticks: list[int] = []
    for option in options:
        if not option.legal_at_distance(distance):
            raise ValueError(f"{option.option_id!r} is illegal at distance {distance}")
        if attack_tick >= tick_window:
            break
        impact_tick = attack_tick + option.impact_delay(distance)
        sequence.append(option.option_id)
        attack_ticks.append(attack_tick)
        if impact_tick < tick_window:
            impact_ticks.append(impact_tick)
            hits.append(option.distribution)
        attack_tick += option.cooldown_ticks
    return FixedSequenceResult(
        tick_window=tick_window,
        distance=distance,
        sequence=tuple(sequence),
        attack_ticks=tuple(attack_ticks),
        impact_ticks=tuple(impact_ticks),
        distribution=convolve_distributions(*hits),
    )


def best_fixed_sequence(
    options: Iterable[AttackOption],
    *,
    target_hp: int,
    tick_window: int,
    distance: int,
) -> FixedSequenceResult:
    """Return the best non-adaptive legal sequence for a fixed KO target."""
    if target_hp < 1:
        raise ValueError("target_hp must be positive")
    ordered = tuple(sorted(options, key=lambda option: option.option_id))
    if not ordered:
        raise ValueError("best_fixed_sequence requires at least one option")
    if len({option.option_id for option in ordered}) != len(ordered):
        raise ValueError("Attack option IDs must be unique")
    if tick_window < 1:
        raise ValueError("tick_window must be positive")

    @cache
    def solve(attack_tick: int) -> FixedSequenceResult:
        best = FixedSequenceResult(
            tick_window=tick_window,
            distance=distance,
            sequence=(),
            attack_ticks=(),
            impact_ticks=(),
            distribution=_delta_distribution(),
        )
        best_probability = best.ko_probability(target_hp)
        for option in ordered:
            if not option.legal_at_distance(distance):
                continue
            impact_tick = attack_tick + option.impact_delay(distance)
            if attack_tick >= tick_window or impact_tick >= tick_window:
                continue
            continuation = solve(attack_tick + option.cooldown_ticks)
            candidate = FixedSequenceResult(
                tick_window=tick_window,
                distance=distance,
                sequence=(option.option_id,) + continuation.sequence,
                attack_ticks=(attack_tick,) + continuation.attack_ticks,
                impact_ticks=(impact_tick,) + continuation.impact_ticks,
                distribution=convolve_distributions(option.distribution, continuation.distribution),
            )
            candidate_probability = candidate.ko_probability(target_hp)
            if candidate_probability > best_probability or (
                candidate_probability == best_probability and _prefer_sequence(candidate.sequence, best.sequence)
            ):
                best = candidate
                best_probability = candidate_probability
        return best

    return solve(0)


def optimal_ko_probability(
    options: Iterable[AttackOption],
    *,
    target_hp: int,
    tick_window: int,
    distance: int,
) -> AdaptiveKOResult:
    """Exact finite-horizon adaptive KO DP for a non-reactive defender.

    The model is intentionally narrower than a full duel: it optimizes only raw
    burst against a static target with perfect observation of resolved impacts.
    """
    if target_hp < 1:
        raise ValueError("target_hp must be positive")
    if tick_window < 1:
        raise ValueError("tick_window must be positive")
    ordered = tuple(
        option for option in sorted(options, key=lambda option: option.option_id) if option.legal_at_distance(distance)
    )
    if not ordered:
        raise ValueError("optimal_ko_probability requires at least one legal option")
    if len({option.option_id for option in ordered}) != len(ordered):
        raise ValueError("Attack option IDs must be unique")
    option_index = {option.option_id: option for option in ordered}

    @cache
    def value(
        tick: int,
        phase: int,
        ready_tick: int,
        remaining_hp: int,
        pending: tuple[tuple[int, str], ...],
    ) -> Fraction:
        if remaining_hp <= 0:
            return Fraction(1)
        if tick >= tick_window:
            return Fraction(0)
        if phase in {0, 2}:
            due = [
                _distribution_from_key(_distribution_key(option_index[option_id].distribution))
                for resolution_tick, option_id in pending
                if resolution_tick == tick
            ]
            future = tuple(item for item in pending if item[0] != tick)
            resolved = convolve_distributions(*due)
            total = Fraction(0)
            for damage, chance in resolved.probability.items():
                total += chance * value(
                    tick if phase == 0 else tick + 1,
                    1 if phase == 0 else 0,
                    ready_tick,
                    max(0, remaining_hp - damage),
                    future,
                )
            return total
        if ready_tick > tick:
            next_due = min(
                (resolution_tick for resolution_tick, _ in pending if resolution_tick > tick), default=ready_tick
            )
            next_tick = min(next_due, ready_tick)
            return value(next_tick, 0, ready_tick, remaining_hp, pending)

        best = value(tick, 2, ready_tick, remaining_hp, pending)
        for option in ordered:
            impact_tick = tick + option.impact_delay(distance)
            next_pending = pending
            if impact_tick < tick_window:
                next_pending = tuple(
                    sorted(
                        pending + ((impact_tick, option.option_id),),
                        key=lambda item: (item[0], item[1]),
                    )
                )
            candidate = value(
                tick,
                2,
                tick + option.cooldown_ticks,
                remaining_hp,
                next_pending,
            )
            if candidate > best:
                best = candidate
        return best

    best_probability = value(0, 0, 0, target_hp, ())
    equally_optimal = []
    for option in ordered:
        impact_tick = option.impact_delay(distance)
        next_pending: tuple[tuple[int, str], ...] = ()
        if impact_tick < tick_window:
            next_pending = ((impact_tick, option.option_id),)
        probability = value(0, 2, option.cooldown_ticks, target_hp, next_pending)
        if probability == best_probability:
            equally_optimal.append(option.option_id)
    equally_optimal_actions = tuple(sorted(equally_optimal))
    return AdaptiveKOResult(
        tick_window=tick_window,
        distance=distance,
        target_hp=target_hp,
        ko_probability=best_probability,
        first_action=equally_optimal_actions[0] if equally_optimal_actions else None,
        equally_optimal_first_actions=equally_optimal_actions,
    )


def survival_probability(distribution: DamageDistribution, hitpoints: int) -> Fraction:
    """Return exact survival probability against a resolved incoming PMF."""
    if hitpoints < 1:
        raise ValueError("hitpoints must be positive")
    return Fraction(1) - _ko_probability(distribution, hitpoints)


def build_combat_envelope(
    candidate_id: str,
    defence_state_id: str,
    options: Iterable[AttackOption],
    *,
    hitpoints: int,
    prayer: int,
    distance: int,
    windows: Iterable[int] = (4, 5, 8, 12),
    hp_thresholds: Iterable[int] = (5, 10, 15, 20, 25, 30),
) -> CombatEnvelope:
    """Materialize exact sustained, window, and stack metrics for Stage 1."""
    if not candidate_id or not defence_state_id:
        raise ValueError("candidate_id and defence_state_id must be non-empty")
    if hitpoints < 1 or prayer < 0:
        raise ValueError("hitpoints must be positive and prayer cannot be negative")
    supplied_options = tuple(sorted(options, key=lambda option: option.option_id))
    if not supplied_options:
        raise ValueError("Combat envelopes require at least one attack option")
    if len({option.option_id for option in supplied_options}) != len(supplied_options):
        raise ValueError("Attack option IDs must be unique")
    ordered_options = tuple(option for option in supplied_options if option.legal_at_distance(distance))
    if not ordered_options:
        raise ValueError(f"No attack option is legal at distance {distance}")
    ordered_windows = tuple(sorted(set(int(window) for window in windows)))
    ordered_thresholds = tuple(sorted(set(int(hp) for hp in hp_thresholds)))
    if not ordered_windows or any(window < 1 for window in ordered_windows):
        raise ValueError("windows must contain positive tick counts")
    if not ordered_thresholds or any(hp < 1 for hp in ordered_thresholds):
        raise ValueError("hp_thresholds must contain positive values")

    fixed_windows = tuple(
        (
            option.option_id,
            fixed_option_window_distribution(option, tick_window=window, distance=distance),
        )
        for option in ordered_options
        for window in ordered_windows
    )
    stacks = tuple(
        StackEnvelopeEntry(
            tick_window=window,
            target_hp=hp,
            best_fixed=best_fixed_sequence(
                ordered_options,
                target_hp=hp,
                tick_window=window,
                distance=distance,
            ),
            adaptive=optimal_ko_probability(
                ordered_options,
                target_hp=hp,
                tick_window=window,
                distance=distance,
            ),
        )
        for window in ordered_windows
        for hp in ordered_thresholds
    )
    signature_payload = {
        "defence_state_id": defence_state_id,
        "hitpoints": hitpoints,
        "prayer": prayer,
        "distance": distance,
        "options": tuple(
            {
                "option_id": option.option_id,
                "damage_type": option.damage_type,
                "cooldown_ticks": option.cooldown_ticks,
                "minimum_distance": option.minimum_distance,
                "maximum_distance": option.maximum_distance,
                "impact_delay_by_distance": tuple(sorted(option.impact_delay_by_distance.items())),
                "distribution": _distribution_key(option.distribution),
                "attack_roll": option.attack_roll,
                "defence_roll": option.defence_roll,
                "hit_chance": option.hit_chance,
                "max_hit": option.max_hit,
            }
            for option in ordered_options
        ),
        "windows": ordered_windows,
        "hp_thresholds": ordered_thresholds,
        "stack_values": tuple(
            (entry.tick_window, entry.target_hp, entry.adaptive.ko_probability, entry.best_fixed.sequence)
            for entry in stacks
        ),
    }
    return CombatEnvelope(
        candidate_id=candidate_id,
        defence_state_id=defence_state_id,
        hitpoints=hitpoints,
        prayer=prayer,
        distance=distance,
        options=ordered_options,
        windows=ordered_windows,
        hp_thresholds=ordered_thresholds,
        fixed_windows=fixed_windows,
        stacks=stacks,
        equivalence_signature=canonical_hash(signature_payload),
    )
