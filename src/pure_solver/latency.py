"""Input-timing model: ``InputTimingProfile`` (perfect, deterministic, distributional or empirical latency) and
``accept_input``, which maps a generated input to the logical tick on which it is accepted.

Verified mechanic primitive that is not yet wired into the ranking pipeline; it is exercised by the test
suite.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum

from .errors import DataUnavailableError, VerifiedMechanicMissingError


class LatencyMode(str, Enum):
    PERFECT = "perfect"
    DETERMINISTIC = "deterministic-latency"
    DISTRIBUTIONAL = "distributional-latency"
    EMPIRICAL = "empirical-latency"


@dataclass(frozen=True)
class InputTimingProfile:
    mode: LatencyMode
    logical_tick_ms: float
    perfect_acceptance_delay_ticks: int = 0
    ping_ms: float = 0.0
    client_delay_ms: float = 0.0
    server_delay_ms: float = 0.0
    ping_samples_ms: tuple[float, ...] = ()
    input_offsets_ms: tuple[float, ...] = ()
    source_ids: tuple[str, ...] = ()
    status: str = "unverified"

    def validate(self, *, allow_experimental: bool = False) -> None:
        accepted = {"verified"}
        if allow_experimental:
            accepted.add("experimental")
        if self.status not in accepted or not self.source_ids:
            raise VerifiedMechanicMissingError("Input timing profile is not approved")
        if self.logical_tick_ms <= 0 or self.perfect_acceptance_delay_ticks < 0:
            raise DataUnavailableError("Input timing profile has invalid tick/delay")
        if any(value < 0 for value in (self.ping_ms, self.client_delay_ms, self.server_delay_ms)):
            raise DataUnavailableError("Latency values cannot be negative")
        if self.mode in {LatencyMode.DISTRIBUTIONAL, LatencyMode.EMPIRICAL} and not self.ping_samples_ms:
            raise DataUnavailableError("Stochastic/empirical latency profile has no ping samples")


@dataclass(frozen=True)
class AcceptedInput:
    generated_tick: int
    generated_offset_ms: float
    accepted_tick: int
    total_delay_ms: float


def accept_input(
    profile: InputTimingProfile,
    *,
    generated_tick: int,
    generated_offset_ms: float,
    rng: random.Random | None = None,
    allow_experimental: bool = False,
) -> AcceptedInput:
    profile.validate(allow_experimental=allow_experimental)
    if generated_tick < 0 or not 0 <= generated_offset_ms < profile.logical_tick_ms:
        raise DataUnavailableError("Input generation time lies outside its logical tick")
    if profile.mode is LatencyMode.PERFECT:
        return AcceptedInput(
            generated_tick,
            generated_offset_ms,
            generated_tick + profile.perfect_acceptance_delay_ticks,
            0.0,
        )
    generator = rng or random.Random(0)
    if profile.mode is LatencyMode.DETERMINISTIC:
        ping = profile.ping_ms
        offset = generated_offset_ms
    else:
        ping = generator.choice(profile.ping_samples_ms)
        offset = generator.choice(profile.input_offsets_ms) if profile.input_offsets_ms else generated_offset_ms
    total = offset + ping + profile.client_delay_ms + profile.server_delay_ms
    accepted_tick = generated_tick + math.ceil(total / profile.logical_tick_ms)
    return AcceptedInput(generated_tick, offset, accepted_tick, total)
