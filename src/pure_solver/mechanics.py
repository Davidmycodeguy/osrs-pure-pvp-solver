"""Verified mechanic records: ``SourceRevision`` provenance, ``Mechanic`` documents with status, sources and
conflicts, and ``MechanicRegistry`` whose ``require``/``evaluate`` raise instead of guessing when a mechanic
is missing, unverified or conflicted.

``pure_math/src/mechanics.rs`` mirrors the ``require`` semantics for the Rust pipeline.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .canonical import canonical_hash
from .errors import DataUnavailableError, MechanicConflictError, VerifiedMechanicMissingError
from .formula import Number, evaluate


@dataclass(frozen=True)
class SourceRevision:
    source_id: str
    url: str
    revision: str
    retrieved_at: str
    content_sha256: str | None = None

    def validate(self) -> None:
        if not self.source_id or not self.url or not self.revision:
            raise DataUnavailableError("Every source record needs source_id, url, and revision")
        try:
            datetime.fromisoformat(self.retrieved_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise DataUnavailableError(f"Invalid source retrieval timestamp: {self.retrieved_at!r}") from error


@dataclass(frozen=True)
class Mechanic:
    mechanic_id: str
    status: str
    value: Any
    formula_version: str
    source_ids: tuple[str, ...]
    test_ids: tuple[str, ...]
    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImpactTiming:
    """Verified logical impact delays for one combat delivery mechanism."""

    impact_delay_by_distance: Mapping[int, int]
    minimum_distance: int
    maximum_distance: int
    source_ids: tuple[str, ...]

    @classmethod
    def from_mechanic(cls, mechanic: Mechanic) -> ImpactTiming:
        if not isinstance(mechanic.value, Mapping):
            raise DataUnavailableError(f"Mechanic {mechanic.mechanic_id!r} must define an impact-timing mapping")
        raw_delays = mechanic.value.get("impact_delay_by_distance")
        if not isinstance(raw_delays, Mapping):
            raise DataUnavailableError(f"Mechanic {mechanic.mechanic_id!r} has no impact-delay table")
        try:
            delays = {int(distance): int(delay) for distance, delay in raw_delays.items()}
            minimum = int(mechanic.value["minimum_distance"])
            maximum = int(mechanic.value["maximum_distance"])
        except (KeyError, TypeError, ValueError) as error:
            raise DataUnavailableError(f"Mechanic {mechanic.mechanic_id!r} has malformed impact timing") from error
        timing = cls(delays, minimum, maximum, mechanic.source_ids)
        timing.validate(mechanic.mechanic_id)
        return timing

    def validate(self, mechanic_id: str = "impact timing") -> None:
        if self.minimum_distance < 1 or self.maximum_distance < self.minimum_distance:
            raise DataUnavailableError(f"Mechanic {mechanic_id!r} has an invalid distance range")
        expected = set(range(self.minimum_distance, self.maximum_distance + 1))
        if set(self.impact_delay_by_distance) != expected:
            raise DataUnavailableError(f"Mechanic {mechanic_id!r} must cover every supported distance exactly")
        if any(delay < 0 for delay in self.impact_delay_by_distance.values()):
            raise DataUnavailableError(f"Mechanic {mechanic_id!r} has a negative impact delay")

    def impact_delay(self, distance: int) -> int:
        try:
            return self.impact_delay_by_distance[distance]
        except KeyError as error:
            raise VerifiedMechanicMissingError(f"No verified impact delay at distance {distance}") from error


class MechanicRegistry:
    def __init__(self, source_records: Mapping[str, SourceRevision], mechanics: Mapping[str, Mechanic]):
        self._sources = dict(source_records)
        self._mechanics = dict(mechanics)
        for source in self._sources.values():
            source.validate()

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> MechanicRegistry:
        sources: dict[str, SourceRevision] = {}
        for item in document.get("sources", []):
            source_id = item["source_id"]
            if source_id in sources:
                raise MechanicConflictError(f"Duplicate source_id {source_id!r} in mechanics document")
            sources[source_id] = SourceRevision(
                source_id=item["source_id"],
                url=item["url"],
                revision=str(item["revision"]),
                retrieved_at=item["retrieved_at"],
                content_sha256=item.get("content_sha256"),
            )
        mechanics: dict[str, Mechanic] = {}
        for item in document.get("mechanics", []):
            mechanic_id = item["mechanic_id"]
            if mechanic_id in mechanics:
                raise MechanicConflictError(f"Duplicate mechanic_id {mechanic_id!r} in mechanics document")
            mechanics[mechanic_id] = Mechanic(
                mechanic_id=item["mechanic_id"],
                status=item.get("status", "unverified"),
                value=item.get("value"),
                formula_version=item.get("formula_version", "unversioned"),
                source_ids=tuple(item.get("source_ids", [])),
                test_ids=tuple(item.get("test_ids", [])),
                conflicts=tuple(item.get("conflicts", [])),
            )
        return cls(sources, mechanics)

    @property
    def source_revisions(self) -> Mapping[str, SourceRevision]:
        return self._sources.copy()

    @property
    def mechanics_hash(self) -> str:
        return canonical_hash(
            {
                "sources": self._sources,
                "mechanics": self._mechanics,
            }
        )

    def require(self, mechanic_id: str) -> Mechanic:
        mechanic = self._mechanics.get(mechanic_id)
        if mechanic is None or mechanic.status != "verified":
            raise VerifiedMechanicMissingError(
                f"Mechanic {mechanic_id!r} is unavailable or not verified; simulation is invalid."
            )
        if mechanic.conflicts:
            raise MechanicConflictError(
                f"Mechanic {mechanic_id!r} has unresolved conflicts: {', '.join(mechanic.conflicts)}"
            )
        if not mechanic.source_ids:
            raise DataUnavailableError(f"Verified mechanic {mechanic_id!r} has no provenance source")
        unknown_sources = set(mechanic.source_ids) - set(self._sources)
        if unknown_sources:
            raise DataUnavailableError(f"Mechanic {mechanic_id!r} names unavailable sources: {sorted(unknown_sources)}")
        if not mechanic.formula_version:
            raise DataUnavailableError(f"Mechanic {mechanic_id!r} has no formula version")
        return mechanic

    def evaluate(self, mechanic_id: str, variables: Mapping[str, Number]) -> Number:
        mechanic = self.require(mechanic_id)
        if not isinstance(mechanic.value, Mapping):
            raise DataUnavailableError(f"Mechanic {mechanic_id!r} does not contain a formula AST")
        return evaluate(mechanic.value, variables)

    def check_required(self, mechanic_ids: list[str] | tuple[str, ...]) -> None:
        for mechanic_id in mechanic_ids:
            self.require(mechanic_id)
