"""Derive verifiable timing claims from empirical experiment documents (range-to-melee traces and the timing
suite), requiring metadata, evidence references and minimum sample counts before any mechanic document is
produced.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import DataUnavailableError, MechanicConflictError


@dataclass(frozen=True)
class RangeToMeleeObservation:
    sample_id: str
    distance_tiles: int
    ranged_attack_tick: int
    ranged_impact_tick: int
    weapon_switch_tick: int
    melee_attack_tick: int
    melee_impact_tick: int
    evidence_ref: str

    @classmethod
    def from_document(cls, raw: Mapping[str, Any]) -> RangeToMeleeObservation:
        required = (
            "sample_id",
            "distance_tiles",
            "ranged_attack_tick",
            "ranged_impact_tick",
            "weapon_switch_tick",
            "melee_attack_tick",
            "melee_impact_tick",
            "evidence_ref",
        )
        missing = [field for field in required if field not in raw]
        if missing:
            raise DataUnavailableError(f"Experiment sample is missing fields: {missing}")
        observation = cls(
            sample_id=str(raw["sample_id"]),
            distance_tiles=int(raw["distance_tiles"]),
            ranged_attack_tick=int(raw["ranged_attack_tick"]),
            ranged_impact_tick=int(raw["ranged_impact_tick"]),
            weapon_switch_tick=int(raw["weapon_switch_tick"]),
            melee_attack_tick=int(raw["melee_attack_tick"]),
            melee_impact_tick=int(raw["melee_impact_tick"]),
            evidence_ref=str(raw["evidence_ref"]),
        )
        ticks = (
            observation.ranged_attack_tick,
            observation.ranged_impact_tick,
            observation.weapon_switch_tick,
            observation.melee_attack_tick,
            observation.melee_impact_tick,
        )
        if observation.distance_tiles < 1 or any(tick < 0 for tick in ticks) or not observation.evidence_ref:
            raise DataUnavailableError("Experiment sample has invalid distance, tick, or evidence reference")
        if observation.ranged_impact_tick < observation.ranged_attack_tick:
            raise DataUnavailableError("Ranged impact cannot precede ranged attack")
        if observation.melee_impact_tick < observation.melee_attack_tick:
            raise DataUnavailableError("Melee impact cannot precede melee attack")
        return observation


@dataclass(frozen=True)
class EmpiricalTimingClaim:
    experiment_id: str
    sample_count: int
    ranged_impact_delay_by_distance: Mapping[int, int]
    melee_impact_delay: int
    switch_and_attack_same_tick: bool
    status: str = "experimental"


@dataclass(frozen=True)
class TimingSuiteClaim:
    experiment_id: str
    tick_pipeline: tuple[str, ...]
    same_tick_ko_by_priority: Mapping[str, str]
    impact_delay_by_kind_and_distance: Mapping[str, Mapping[int, int]]
    sample_counts: Mapping[str, int]
    status: str = "experimental"

    def mechanic_documents(self) -> tuple[Mapping[str, Any], ...]:
        projectile = self.impact_delay_by_kind_and_distance
        return (
            {"mechanic_id": "tick.pipeline", "status": self.status, "value": list(self.tick_pipeline)},
            {
                "mechanic_id": "death.simultaneous_ko",
                "status": self.status,
                "value": dict(self.same_tick_ko_by_priority),
            },
            {"mechanic_id": "melee.damage_timing", "status": self.status, "value": dict(projectile.get("melee", {}))},
            {
                "mechanic_id": "ranged.projectile_timing",
                "status": self.status,
                "value": dict(projectile.get("ranged", {})),
            },
            {
                "mechanic_id": "magic.projectile_timing",
                "status": self.status,
                "value": dict(projectile.get("magic", {})),
            },
        )


def derive_range_to_melee_claim(
    document: Mapping[str, Any],
    *,
    minimum_samples_per_distance: int = 20,
) -> EmpiricalTimingClaim:
    metadata_fields = (
        "experiment_id",
        "game_version",
        "date",
        "world",
        "conditions",
        "inputs",
        "expected_outcome",
        "observed_outcome",
        "conclusion",
    )
    missing = [field for field in metadata_fields if not document.get(field)]
    if missing:
        raise DataUnavailableError(f"Experiment record is missing required metadata: {missing}")
    observations = tuple(RangeToMeleeObservation.from_document(raw) for raw in document.get("observations", []))
    if not observations:
        raise DataUnavailableError("Experiment record contains no observations")

    ranged_by_distance: dict[int, set[int]] = {}
    sample_counts: dict[int, int] = {}
    melee_delays: set[int] = set()
    switch_same_tick: set[bool] = set()
    for observation in observations:
        ranged_by_distance.setdefault(observation.distance_tiles, set()).add(
            observation.ranged_impact_tick - observation.ranged_attack_tick
        )
        sample_counts[observation.distance_tiles] = sample_counts.get(observation.distance_tiles, 0) + 1
        melee_delays.add(observation.melee_impact_tick - observation.melee_attack_tick)
        switch_same_tick.add(observation.weapon_switch_tick == observation.melee_attack_tick)

    conflicting_distances = {
        distance: sorted(delays) for distance, delays in ranged_by_distance.items() if len(delays) != 1
    }
    if conflicting_distances or len(melee_delays) != 1 or len(switch_same_tick) != 1:
        raise MechanicConflictError(
            "Experiment observations disagree: "
            f"ranged={conflicting_distances}, melee={sorted(melee_delays)}, "
            f"switch_same_tick={sorted(switch_same_tick)}"
        )
    insufficient = {
        distance: count for distance, count in sample_counts.items() if count < minimum_samples_per_distance
    }
    if insufficient:
        raise DataUnavailableError(f"Experiment has insufficient repeated samples per distance: {insufficient}")
    return EmpiricalTimingClaim(
        experiment_id=str(document["experiment_id"]),
        sample_count=len(observations),
        ranged_impact_delay_by_distance={
            distance: next(iter(delays)) for distance, delays in sorted(ranged_by_distance.items())
        },
        melee_impact_delay=next(iter(melee_delays)),
        switch_and_attack_same_tick=next(iter(switch_same_tick)),
    )


def derive_timing_suite_claim(
    document: Mapping[str, Any],
    *,
    minimum_samples_per_case: int = 20,
) -> TimingSuiteClaim:
    experiment_id = str(document.get("experiment_id", ""))
    if not experiment_id or not document.get("game_version") or not document.get("evidence_manifest"):
        raise DataUnavailableError("Timing suite lacks experiment ID, game version, or evidence manifest")

    pipeline_samples = tuple(tuple(map(str, sample)) for sample in document.get("tick_pipeline_samples", ()))
    if len(pipeline_samples) < minimum_samples_per_case or not pipeline_samples:
        raise DataUnavailableError("Timing suite has insufficient tick-pipeline samples")
    unique_pipelines = set(pipeline_samples)
    if len(unique_pipelines) != 1:
        raise MechanicConflictError(f"Tick-pipeline samples conflict: {sorted(unique_pipelines)}")
    pipeline = next(iter(unique_pipelines))

    ko_values: dict[str, set[str]] = {}
    ko_counts: dict[str, int] = {}
    for sample in document.get("same_tick_ko_samples", ()):
        priority = str(sample.get("priority", ""))
        outcome = str(sample.get("outcome", ""))
        evidence = str(sample.get("evidence_ref", ""))
        if (
            priority not in {"player", "opponent"}
            or outcome not in {"player_win", "opponent_win", "draw"}
            or not evidence
        ):
            raise DataUnavailableError("Same-tick KO sample is invalid")
        ko_values.setdefault(priority, set()).add(outcome)
        ko_counts[priority] = ko_counts.get(priority, 0) + 1
    if set(ko_counts) != {"player", "opponent"} or any(
        count < minimum_samples_per_case for count in ko_counts.values()
    ):
        raise DataUnavailableError(f"Same-tick KO samples are insufficient: {ko_counts}")
    conflicts = {key: sorted(values) for key, values in ko_values.items() if len(values) != 1}
    if conflicts:
        raise MechanicConflictError(f"Same-tick KO samples conflict: {conflicts}")

    delays: dict[str, dict[int, set[int]]] = {}
    delay_counts: dict[tuple[str, int], int] = {}
    for sample in document.get("impact_samples", ()):
        kind = str(sample.get("kind", ""))
        distance = int(sample.get("distance_tiles", 0))
        attack_tick = int(sample.get("attack_tick", -1))
        impact_tick = int(sample.get("impact_tick", -1))
        evidence = str(sample.get("evidence_ref", ""))
        if (
            kind not in {"melee", "ranged", "magic"}
            or distance < 1
            or attack_tick < 0
            or impact_tick < attack_tick
            or not evidence
        ):
            raise DataUnavailableError("Impact timing sample is invalid")
        delays.setdefault(kind, {}).setdefault(distance, set()).add(impact_tick - attack_tick)
        delay_counts[(kind, distance)] = delay_counts.get((kind, distance), 0) + 1
    required_kinds = {"melee", "ranged", "magic"}
    if set(delays) != required_kinds:
        raise DataUnavailableError(f"Impact samples omit kinds: {sorted(required_kinds - set(delays))}")
    insufficient = {
        f"{kind}:{distance}": count
        for (kind, distance), count in delay_counts.items()
        if count < minimum_samples_per_case
    }
    if insufficient:
        raise DataUnavailableError(f"Impact samples are insufficient: {insufficient}")
    delay_conflicts = {
        f"{kind}:{distance}": sorted(values)
        for kind, by_distance in delays.items()
        for distance, values in by_distance.items()
        if len(values) != 1
    }
    if delay_conflicts:
        raise MechanicConflictError(f"Impact samples conflict: {delay_conflicts}")
    resolved_delays = {
        kind: {distance: next(iter(values)) for distance, values in sorted(by_distance.items())}
        for kind, by_distance in sorted(delays.items())
    }
    counts = {
        "tick_pipeline": len(pipeline_samples),
        **{f"ko:{key}": value for key, value in sorted(ko_counts.items())},
        **{f"impact:{kind}:{distance}": count for (kind, distance), count in sorted(delay_counts.items())},
    }
    return TimingSuiteClaim(
        experiment_id=experiment_id,
        tick_pipeline=pipeline,
        same_tick_ko_by_priority={key: next(iter(values)) for key, values in sorted(ko_values.items())},
        impact_delay_by_kind_and_distance=resolved_delays,
        sample_counts=counts,
    )
