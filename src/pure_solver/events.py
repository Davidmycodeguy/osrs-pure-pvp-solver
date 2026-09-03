"""Generic tick engine: fighter and combat state, pending damage ordered by resolution tick and sequence, and a
``TickEngine`` whose phase order and simultaneous-KO rule come from the verified mechanics snapshot.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Protocol

from .errors import DataUnavailableError
from .mechanics import MechanicRegistry


class TerminalStatus(str, Enum):
    ACTIVE = "active"
    PLAYER_WIN = "player_win"
    OPPONENT_WIN = "opponent_win"
    DRAW = "draw"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class FighterState:
    hp: int
    max_hp: int
    attack_ready_tick: int = 0
    eat_ready_tick: int = 0

    def with_damage(self, damage: int) -> FighterState:
        return replace(self, hp=self.hp - damage)


@dataclass(frozen=True, order=True)
class PendingDamage:
    resolution_tick: int
    sequence: int
    source: str = field(compare=False)
    target: str = field(compare=False)
    amount: int = field(compare=False)
    creation_tick: int = field(compare=False)


@dataclass(frozen=True)
class CombatState:
    tick: int
    player: FighterState
    opponent: FighterState
    pending_damage: tuple[PendingDamage, ...] = ()
    terminal_status: TerminalStatus = TerminalStatus.ACTIVE
    action_history: tuple[str, ...] = ()


class Policy(Protocol):
    def action(self, state: CombatState, actor: str) -> str | None: ...


@dataclass(frozen=True)
class TickPipeline:
    phases: tuple[str, ...]
    priority_order: tuple[str, ...]

    @classmethod
    def from_mechanics(cls, mechanics: MechanicRegistry) -> TickPipeline:
        mechanic = mechanics.require("tick.pipeline")
        value = mechanic.value
        if isinstance(value, list):
            # Legacy fixtures retain their original compact representation; real
            # rulesets must specify their player-versus-player priority.
            phases = tuple(value)
            priority_order = ("player", "opponent")
        elif isinstance(value, Mapping):
            raw_phases = value.get("phases")
            raw_priority = value.get("priority_order")
            if not isinstance(raw_phases, list) or not isinstance(raw_priority, list):
                raise DataUnavailableError("tick.pipeline must define phase and priority lists")
            phases = tuple(map(str, raw_phases))
            priority_order = tuple(map(str, raw_priority))
        else:
            raise DataUnavailableError("tick.pipeline must be a data-defined list or mapping")
        pipeline = cls(phases, priority_order)
        pipeline.validate()
        return pipeline

    def validate(self) -> None:
        allowed = {"resolve_pending_damage", "record_actions", "check_terminal"}
        if not self.phases or set(self.phases) - allowed or len(set(self.phases)) != len(self.phases):
            raise DataUnavailableError("tick.pipeline contains invalid engine phases")
        if set(self.priority_order) != {"player", "opponent"}:
            raise DataUnavailableError("tick.pipeline must define player and opponent priority exactly once")


class TickEngine:
    """Deterministic event resolver whose ordering is configured by the ruleset.

    This class deliberately knows no OSRS timing constants. Construction fails
    until a verified tick pipeline and a simultaneous-KO payoff are present in
    the immutable mechanics snapshot.
    """

    def __init__(self, mechanics: MechanicRegistry):
        self._mechanics = mechanics
        self._pipeline = TickPipeline.from_mechanics(mechanics)
        self._simultaneous_ko = mechanics.require("death.simultaneous_ko").value
        if self._simultaneous_ko not in {"draw", "player_win", "opponent_win"}:
            raise DataUnavailableError("death.simultaneous_ko must define a configured terminal payoff")

    @staticmethod
    def schedule_damage(state: CombatState, event: PendingDamage) -> CombatState:
        pending = list(state.pending_damage)
        heapq.heappush(pending, event)
        return replace(state, pending_damage=tuple(pending))

    def step(self, state: CombatState, actions: Iterable[str] = ()) -> CombatState:
        if state.terminal_status is not TerminalStatus.ACTIVE:
            return state
        current = state
        for phase in self._pipeline.phases:
            if phase == "resolve_pending_damage":
                current = self._resolve_due_damage(current)
            elif phase == "record_actions":
                current = replace(current, action_history=current.action_history + tuple(actions))
            elif phase == "check_terminal":
                current = self._check_terminal(current)
            else:
                raise DataUnavailableError(f"tick.pipeline contains unknown engine phase {phase!r}")
            if current.terminal_status is not TerminalStatus.ACTIVE:
                return current
        return replace(current, tick=current.tick + 1)

    def _resolve_due_damage(self, state: CombatState) -> CombatState:
        due: list[PendingDamage] = []
        future: list[PendingDamage] = []
        for event in state.pending_damage:
            (due if event.resolution_tick == state.tick else future).append(event)
        player = state.player
        opponent = state.opponent
        priority = {actor: index for index, actor in enumerate(self._pipeline.priority_order)}
        for event in sorted(due, key=lambda event: (priority.get(event.source, -1), event.sequence)):
            if event.source not in priority:
                raise DataUnavailableError(f"Damage event has an unknown source: {event.source!r}")
            if event.source == "player" and player.hp <= 0:
                continue
            if event.source == "opponent" and opponent.hp <= 0:
                continue
            if event.target == "player":
                player = player.with_damage(event.amount)
            elif event.target == "opponent":
                opponent = opponent.with_damage(event.amount)
            else:
                raise DataUnavailableError(f"Damage event has an unknown target: {event.target!r}")
        return replace(state, player=player, opponent=opponent, pending_damage=tuple(future))

    def _check_terminal(self, state: CombatState) -> CombatState:
        player_dead = state.player.hp <= 0
        opponent_dead = state.opponent.hp <= 0
        if player_dead and opponent_dead:
            return replace(state, terminal_status=TerminalStatus(self._simultaneous_ko))
        if player_dead:
            return replace(state, terminal_status=TerminalStatus.OPPONENT_WIN)
        if opponent_dead:
            return replace(state, terminal_status=TerminalStatus.PLAYER_WIN)
        return state
