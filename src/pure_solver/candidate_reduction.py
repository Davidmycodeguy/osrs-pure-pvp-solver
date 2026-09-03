"""Exact-duplicate removal, Pareto pruning and diverse seed selection over ``ReductionCandidate`` metric vectors,
with an audit record for every removal and every preserved capability niche.

Ported to Rust as ``pure_math/src/reduction.rs``; this module is the golden reference.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from math import isfinite, sqrt

from .combat_envelope import CombatEnvelope

MetricValue = int | float | Fraction


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return tuple((str(key), _freeze(item)) for key, item in sorted(value.items(), key=lambda entry: str(entry[0])))
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_freeze(item) for item in value), key=repr))
    return value


def _metric_value_key(value: MetricValue) -> tuple[int, int | float]:
    if isinstance(value, Fraction):
        return (0, float(value))
    if isinstance(value, int):
        return (1, value)
    return (2, value)


@dataclass(frozen=True, init=False)
class ReductionCandidate:
    candidate_id: str
    equivalence_signature: object
    comparison_class: object
    normalized_metrics: tuple[tuple[str, MetricValue], ...]
    capabilities: tuple[str, ...]

    def __init__(
        self,
        candidate_id: str,
        equivalence_signature: object,
        comparison_class: object,
        normalized_metrics: Mapping[str, MetricValue],
        capabilities: Iterable[str] = (),
    ) -> None:
        metrics = tuple(
            (str(name), value) for name, value in sorted(normalized_metrics.items(), key=lambda entry: str(entry[0]))
        )
        if not metrics:
            raise ValueError("Reduction candidates need at least one normalized metric")
        if any(isinstance(value, float) and not isfinite(value) for _, value in metrics):
            raise ValueError("Normalized metrics must be finite")
        names = [name for name, _ in metrics]
        if len(set(names)) != len(names):
            raise ValueError("Metric names must be unique")
        cleaned_capabilities = tuple(sorted({str(token) for token in capabilities}))
        object.__setattr__(self, "candidate_id", str(candidate_id))
        object.__setattr__(self, "equivalence_signature", _freeze(equivalence_signature))
        object.__setattr__(self, "comparison_class", _freeze(comparison_class))
        object.__setattr__(self, "normalized_metrics", metrics)
        object.__setattr__(self, "capabilities", cleaned_capabilities)

    @property
    def metric_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.normalized_metrics)

    @property
    def metric_map(self) -> Mapping[str, MetricValue]:
        return dict(self.normalized_metrics)

    def to_document(self) -> Mapping[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "equivalence_signature": self.equivalence_signature,
            "comparison_class": self.comparison_class,
            "normalized_metrics": dict(self.normalized_metrics),
            "capabilities": self.capabilities,
        }


def candidate_from_combat_envelopes(
    candidate_id: str,
    envelopes: Iterable[CombatEnvelope],
    *,
    comparison_class: object,
    additional_metrics: Mapping[str, MetricValue] | None = None,
    capabilities: Iterable[str] = (),
) -> ReductionCandidate:
    """Combine exact defender-state envelopes into one reduction record.

    Callers should put inventory cost, resource state, and action-emulation
    requirements in ``comparison_class`` or ``capabilities``. Representative or
    heuristic metrics may be useful for seed ordering, but must not be passed
    here when they are not safe dominance dimensions.
    """
    records = tuple(sorted(envelopes, key=lambda envelope: envelope.defence_state_id))
    if not records:
        raise ValueError("At least one combat envelope is required")
    if any(envelope.candidate_id != candidate_id for envelope in records):
        raise ValueError("All combat envelopes must belong to candidate_id")
    if len({envelope.defence_state_id for envelope in records}) != len(records):
        raise ValueError("Defence-state IDs must be unique per reduction candidate")
    metrics: dict[str, MetricValue] = {}
    capability_tokens = {str(token) for token in capabilities}
    for envelope in records:
        capability_tokens.update(envelope.capabilities)
        for name, value in envelope.normalized_metrics.items():
            metrics[f"{envelope.defence_state_id}:{name}"] = value
    for name, value in (additional_metrics or {}).items():
        key = str(name)
        if key in metrics:
            raise ValueError(f"Additional metric {key!r} conflicts with an envelope metric")
        metrics[key] = value
    equivalence_signature = {
        "defence_states": tuple((envelope.defence_state_id, envelope.equivalence_signature) for envelope in records),
        "additional_metrics": tuple(sorted((additional_metrics or {}).items())),
        "capabilities": tuple(sorted(capability_tokens)),
    }
    return ReductionCandidate(
        candidate_id,
        equivalence_signature,
        comparison_class,
        metrics,
        capability_tokens,
    )


@dataclass(frozen=True)
class ExactDuplicateAudit:
    removed_candidate_id: str
    surviving_candidate_id: str
    equivalence_signature: object
    comparison_class: object
    reason: str

    def to_document(self) -> Mapping[str, object]:
        return {
            "removed_candidate_id": self.removed_candidate_id,
            "surviving_candidate_id": self.surviving_candidate_id,
            "equivalence_signature": self.equivalence_signature,
            "comparison_class": self.comparison_class,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DominanceAudit:
    removed_candidate_id: str
    surviving_candidate_id: str
    comparison_class: object
    metric_names: tuple[str, ...]
    removed_capabilities: tuple[str, ...]
    surviving_capabilities: tuple[str, ...]
    reason: str

    def to_document(self) -> Mapping[str, object]:
        return {
            "removed_candidate_id": self.removed_candidate_id,
            "surviving_candidate_id": self.surviving_candidate_id,
            "comparison_class": self.comparison_class,
            "metric_names": self.metric_names,
            "removed_capabilities": self.removed_capabilities,
            "surviving_capabilities": self.surviving_capabilities,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CapabilityNiche:
    capability: str
    representative_candidate_id: str
    frequency: int

    def to_document(self) -> Mapping[str, object]:
        return {
            "capability": self.capability,
            "representative_candidate_id": self.representative_candidate_id,
            "frequency": self.frequency,
        }


@dataclass(frozen=True)
class ReductionCounts:
    starting_candidates: int
    exact_duplicates_removed: int
    dominated_candidates_removed: int
    remaining_pareto_candidates: int

    def to_document(self) -> Mapping[str, int]:
        return {
            "starting_candidates": self.starting_candidates,
            "exact_duplicates_removed": self.exact_duplicates_removed,
            "dominated_candidates_removed": self.dominated_candidates_removed,
            "remaining_pareto_candidates": self.remaining_pareto_candidates,
        }


@dataclass(frozen=True)
class CandidateReductionResult:
    retained_candidates: tuple[ReductionCandidate, ...]
    exact_duplicate_audits: tuple[ExactDuplicateAudit, ...]
    dominance_audits: tuple[DominanceAudit, ...]
    preserved_capability_niches: tuple[CapabilityNiche, ...]
    counts: ReductionCounts

    def to_document(self) -> Mapping[str, object]:
        return {
            "counts": self.counts.to_document(),
            "retained_candidates": tuple(candidate.to_document() for candidate in self.retained_candidates),
            "exact_duplicate_audits": tuple(record.to_document() for record in self.exact_duplicate_audits),
            "dominance_audits": tuple(record.to_document() for record in self.dominance_audits),
            "preserved_capability_niches": tuple(record.to_document() for record in self.preserved_capability_niches),
        }


@dataclass(frozen=True)
class SeedReason:
    candidate_id: str
    reasons: tuple[str, ...]

    def to_document(self) -> Mapping[str, object]:
        return {"candidate_id": self.candidate_id, "reasons": self.reasons}


@dataclass(frozen=True)
class DiverseSeedSelection:
    requested_size: int
    selected_candidates: tuple[ReductionCandidate, ...]
    reasons: tuple[SeedReason, ...]

    def to_document(self) -> Mapping[str, object]:
        return {
            "requested_size": self.requested_size,
            "selected_candidates": tuple(candidate.to_document() for candidate in self.selected_candidates),
            "reasons": tuple(reason.to_document() for reason in self.reasons),
        }


def _candidate_sort_key(candidate: ReductionCandidate) -> tuple[object, ...]:
    metric_values = tuple(_metric_value_key(value) for _, value in candidate.normalized_metrics)
    return (
        candidate.comparison_class,
        candidate.metric_names,
        tuple(-value[1] for value in metric_values),
        -len(candidate.capabilities),
        candidate.capabilities,
        candidate.candidate_id,
    )


def _dominates(left: ReductionCandidate, right: ReductionCandidate) -> bool:
    if left.candidate_id == right.candidate_id:
        return False
    if left.comparison_class != right.comparison_class or left.metric_names != right.metric_names:
        return False
    left_capabilities = set(left.capabilities)
    right_capabilities = set(right.capabilities)
    if not left_capabilities.issuperset(right_capabilities):
        return False
    weakly_better = True
    strictly_better = left_capabilities > right_capabilities
    for (_, left_value), (_, right_value) in zip(left.normalized_metrics, right.normalized_metrics):
        if left_value < right_value:
            weakly_better = False
            break
        if left_value > right_value:
            strictly_better = True
    return weakly_better and strictly_better


def deduplicate_candidates(
    candidates: Iterable[ReductionCandidate],
) -> tuple[tuple[ReductionCandidate, ...], tuple[ExactDuplicateAudit, ...]]:
    # Treat the caller-provided behavior signature as necessary but not
    # sufficient.  Requiring the resolved metrics and capability/action set to
    # match here prevents an incomplete signature from silently deleting a KO,
    # defence, range, or style specialist.
    grouped: dict[tuple[object, object, object, object], list[ReductionCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(
            (
                candidate.equivalence_signature,
                candidate.comparison_class,
                candidate.normalized_metrics,
                candidate.capabilities,
            ),
            [],
        ).append(candidate)

    survivors: list[ReductionCandidate] = []
    audits: list[ExactDuplicateAudit] = []
    for key in sorted(grouped, key=lambda item: repr(item)):
        records = sorted(grouped[key], key=_candidate_sort_key)
        survivor = min(records, key=_candidate_sort_key)
        survivors.append(survivor)
        for candidate in records:
            if candidate.candidate_id == survivor.candidate_id:
                continue
            audits.append(
                ExactDuplicateAudit(
                    removed_candidate_id=candidate.candidate_id,
                    surviving_candidate_id=survivor.candidate_id,
                    equivalence_signature=survivor.equivalence_signature,
                    comparison_class=survivor.comparison_class,
                    reason="exact combat-equivalent signature",
                )
            )
    return tuple(sorted(survivors, key=_candidate_sort_key)), tuple(
        sorted(
            audits,
            key=lambda record: (
                record.surviving_candidate_id,
                record.removed_candidate_id,
            ),
        )
    )


def pareto_prune_candidates(
    candidates: Iterable[ReductionCandidate],
) -> tuple[tuple[ReductionCandidate, ...], tuple[DominanceAudit, ...]]:
    groups: dict[tuple[object, tuple[str, ...]], list[ReductionCandidate]] = {}
    for candidate in candidates:
        groups.setdefault((candidate.comparison_class, candidate.metric_names), []).append(candidate)

    survivors: list[ReductionCandidate] = []
    audits: list[DominanceAudit] = []
    for key in sorted(groups, key=lambda item: repr(item)):
        frontier: list[ReductionCandidate] = []
        ordered = sorted(groups[key], key=_candidate_sort_key)
        for candidate in ordered:
            if any(_dominates(other, candidate) for other in frontier):
                continue
            next_frontier = [existing for existing in frontier if not _dominates(candidate, existing)]
            next_frontier.append(candidate)
            frontier = sorted(next_frontier, key=_candidate_sort_key)

        frontier_ids = {candidate.candidate_id for candidate in frontier}
        for candidate in ordered:
            if candidate.candidate_id in frontier_ids:
                continue
            # Component-wise dominance and capability inclusion are transitive,
            # so every removed record has at least one final-frontier dominator.
            dominator = min(
                (other for other in frontier if _dominates(other, candidate)),
                key=_candidate_sort_key,
            )
            audits.append(
                DominanceAudit(
                    removed_candidate_id=candidate.candidate_id,
                    surviving_candidate_id=dominator.candidate_id,
                    comparison_class=candidate.comparison_class,
                    metric_names=candidate.metric_names,
                    removed_capabilities=candidate.capabilities,
                    surviving_capabilities=dominator.capabilities,
                    reason=(
                        "same comparison class and metric dimensions; every metric is weakly better; "
                        "capabilities are a superset; at least one combat dimension is strictly better"
                    ),
                )
            )
        survivors.extend(frontier)
    return tuple(sorted(survivors, key=_candidate_sort_key)), tuple(
        sorted(
            audits,
            key=lambda record: (
                record.surviving_candidate_id,
                record.removed_candidate_id,
            ),
        )
    )


def _capability_niches(candidates: Iterable[ReductionCandidate]) -> tuple[CapabilityNiche, ...]:
    retained = tuple(candidates)
    frequencies: dict[str, int] = {}
    for candidate in retained:
        for capability in candidate.capabilities:
            frequencies[capability] = frequencies.get(capability, 0) + 1
    niches: list[CapabilityNiche] = []
    for capability in sorted(frequencies):
        representatives = [candidate for candidate in retained if capability in candidate.capabilities]
        best = min(
            representatives,
            key=lambda candidate: (
                tuple(-float(value) for _, value in candidate.normalized_metrics),
                -len(candidate.capabilities),
                candidate.candidate_id,
            ),
        )
        niches.append(CapabilityNiche(capability, best.candidate_id, frequencies[capability]))
    return tuple(niches)


def reduce_candidates(candidates: Iterable[ReductionCandidate]) -> CandidateReductionResult:
    ordered_input = tuple(candidates)
    deduped, duplicate_audits = deduplicate_candidates(ordered_input)
    pruned, dominance_audits = pareto_prune_candidates(deduped)
    return CandidateReductionResult(
        retained_candidates=pruned,
        exact_duplicate_audits=duplicate_audits,
        dominance_audits=dominance_audits,
        preserved_capability_niches=_capability_niches(pruned),
        counts=ReductionCounts(
            starting_candidates=len(ordered_input),
            exact_duplicates_removed=len(duplicate_audits),
            dominated_candidates_removed=len(dominance_audits),
            remaining_pareto_candidates=len(pruned),
        ),
    )


def _normalized_vectors(
    candidates: tuple[ReductionCandidate, ...],
) -> tuple[tuple[str, ...], dict[str, tuple[float, ...]]]:
    metric_names = tuple(sorted({name for candidate in candidates for name in candidate.metric_names}))
    metric_bounds: dict[str, tuple[float, float]] = {}
    for name in metric_names:
        values = [float(candidate.metric_map[name]) for candidate in candidates if name in candidate.metric_map]
        metric_bounds[name] = (min(values), max(values))
    vectors: dict[str, tuple[float, ...]] = {}
    for candidate in candidates:
        metrics = candidate.metric_map
        vector: list[float] = []
        for name in metric_names:
            lower, upper = metric_bounds[name]
            if name not in metrics:
                vector.append(0.0)
                continue
            value = float(metrics[name])
            if upper == lower:
                vector.append(1.0)
                continue
            vector.append((value - lower) / (upper - lower))
        vectors[candidate.candidate_id] = tuple(vector)
    return metric_names, vectors


def _distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sqrt(sum((left_value - right_value) ** 2 for left_value, right_value in zip(left, right)))


def _coverage_score(candidate: ReductionCandidate, vector: tuple[float, ...]) -> tuple[float, int, str]:
    return (sum(vector), len(candidate.capabilities), candidate.candidate_id)


def _capability_priority(token: str) -> tuple[int, str]:
    family, _, _ = token.partition(":")
    priorities = {
        "style": 0,
        "defence": 1,
        "range": 2,
        "switch": 3,
    }
    return (priorities.get(family, 4), token)


def select_diverse_seeds(candidates: Iterable[ReductionCandidate], requested_size: int) -> DiverseSeedSelection:
    if requested_size < 1:
        raise ValueError("requested_size must be positive")
    pool = tuple(sorted(candidates, key=_candidate_sort_key))
    if not pool:
        raise ValueError("Seed selection requires at least one candidate")

    metric_names, vectors = _normalized_vectors(pool)
    selected: list[ReductionCandidate] = []
    reasons: dict[str, list[str]] = {}

    def add(candidate: ReductionCandidate, reason: str) -> None:
        if candidate.candidate_id in reasons:
            reasons[candidate.candidate_id].append(reason)
            return
        if len(selected) >= requested_size:
            return
        selected.append(candidate)
        reasons[candidate.candidate_id] = [reason]

    for metric_name in metric_names:
        eligible = [candidate for candidate in pool if metric_name in candidate.metric_map]
        extreme = min(
            eligible,
            key=lambda candidate: (
                -float(candidate.metric_map[metric_name]),
                -sum(vectors[candidate.candidate_id]),
                -len(candidate.capabilities),
                candidate.candidate_id,
            ),
        )
        add(extreme, f"metric_extreme:{metric_name}")
        if len(selected) >= requested_size:
            break

    if len(selected) < requested_size:
        frequencies: dict[str, int] = {}
        for candidate in pool:
            for capability in candidate.capabilities:
                frequencies[capability] = frequencies.get(capability, 0) + 1
        for capability in sorted(
            frequencies,
            key=lambda token: (frequencies[token], _capability_priority(token)),
        ):
            niche = min(
                [candidate for candidate in pool if capability in candidate.capabilities],
                key=lambda candidate: (
                    -sum(vectors[candidate.candidate_id]),
                    -len(candidate.capabilities),
                    candidate.candidate_id,
                ),
            )
            add(niche, f"capability_niche:{capability}")
            if len(selected) >= requested_size:
                break

    while len(selected) < min(requested_size, len(pool)):
        remaining = [candidate for candidate in pool if candidate.candidate_id not in reasons]
        if not selected:
            best = min(
                remaining,
                key=lambda candidate: (
                    -sum(vectors[candidate.candidate_id]),
                    -len(candidate.capabilities),
                    candidate.candidate_id,
                ),
            )
            add(best, "coverage_anchor")
            continue
        best_candidate = max(
            remaining,
            key=lambda candidate: (
                min(
                    _distance(vectors[candidate.candidate_id], vectors[selected_candidate.candidate_id])
                    for selected_candidate in selected
                ),
                _coverage_score(candidate, vectors[candidate.candidate_id]),
            ),
        )
        add(best_candidate, "coverage_farthest_point")

    return DiverseSeedSelection(
        requested_size=requested_size,
        selected_candidates=tuple(selected),
        reasons=tuple(
            SeedReason(candidate.candidate_id, tuple(reasons[candidate.candidate_id])) for candidate in selected
        ),
    )
