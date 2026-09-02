"""Tile movement primitives: ``Tile`` distances, a ``MovementProfile`` from verified mechanics, per-tick movement
resolution.

Verified mechanic primitive that is not yet wired into the ranking pipeline; it is exercised by the test
suite.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .errors import DataUnavailableError, VerifiedMechanicMissingError
from .mechanics import MechanicRegistry


@dataclass(frozen=True, order=True)
class Tile:
    x: int
    y: int
    plane: int = 0

    def distance(self, other: Tile, metric: str = "chebyshev") -> int:
        if self.plane != other.plane:
            raise DataUnavailableError("Distance across planes is unavailable")
        dx, dy = abs(self.x - other.x), abs(self.y - other.y)
        if metric == "chebyshev":
            return max(dx, dy)
        if metric == "manhattan":
            return dx + dy
        raise DataUnavailableError(f"Unknown distance metric {metric!r}")


@dataclass(frozen=True)
class MovementProfile:
    walk_tiles_per_tick: int
    run_tiles_per_tick: int
    distance_metric: str
    diagonal_allowed: bool
    source_ids: tuple[str, ...]
    status: str = "unverified"

    @classmethod
    def from_mechanics(cls, mechanics: MechanicRegistry) -> MovementProfile:
        mechanic = mechanics.require("movement.resolution")
        if not isinstance(mechanic.value, dict):
            raise DataUnavailableError("movement.resolution must be a mapping")
        return cls(
            walk_tiles_per_tick=int(mechanic.value["walk_tiles_per_tick"]),
            run_tiles_per_tick=int(mechanic.value["run_tiles_per_tick"]),
            distance_metric=str(mechanic.value["distance_metric"]),
            diagonal_allowed=bool(mechanic.value["diagonal_allowed"]),
            source_ids=mechanic.source_ids,
            status=mechanic.status,
        )

    def validate(self) -> None:
        if self.status != "verified" or not self.source_ids:
            raise VerifiedMechanicMissingError("Movement resolution profile is not verified")
        if self.walk_tiles_per_tick < 1 or self.run_tiles_per_tick < self.walk_tiles_per_tick:
            raise DataUnavailableError("Movement profile has invalid per-tick speeds")
        if self.distance_metric not in {"chebyshev", "manhattan"}:
            raise DataUnavailableError("Movement profile has invalid distance metric")


@dataclass(frozen=True)
class MovementState:
    tile: Tile
    destination: Tile | None = None
    running: bool = False
    bound_until_tick: int = 0


def _step(current: Tile, target: Tile, diagonal: bool) -> Tile:
    dx = (target.x > current.x) - (target.x < current.x)
    dy = (target.y > current.y) - (target.y < current.y)
    if not diagonal and dx and dy:
        dy = 0
    return Tile(current.x + dx, current.y + dy, current.plane)


def resolve_movement_tick(
    state: MovementState,
    profile: MovementProfile,
    *,
    tick: int,
    blocked_tiles: frozenset[Tile] = frozenset(),
) -> MovementState:
    profile.validate()
    if state.destination is None or state.tile == state.destination or tick < state.bound_until_tick:
        return state
    if state.tile.plane != state.destination.plane:
        raise DataUnavailableError("Movement destination is on another plane")
    steps = profile.run_tiles_per_tick if state.running else profile.walk_tiles_per_tick
    tile = state.tile
    for _ in range(steps):
        candidate = _step(tile, state.destination, profile.diagonal_allowed)
        if candidate in blocked_tiles:
            break
        tile = candidate
        if tile == state.destination:
            break
    return replace(state, tile=tile, destination=None if tile == state.destination else state.destination)
