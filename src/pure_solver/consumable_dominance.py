"""Dominance pruning over verified F2P food documents: a food is dropped only when another food matches or beats
it at every step of its eat lifecycle (healing, eat delay, attack delay); foods with effects or byproducts are
never compared, and every removal is recorded.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .errors import DataUnavailableError
from .legality import F2P_STANDARD_WORLD_SCOPE


@dataclass(frozen=True)
class FoodOption:
    consumable_id: str
    initial_state: str


@dataclass(frozen=True)
class FoodDominanceRecord:
    dominated_consumable_id: str
    dominating_consumable_id: str
    reason: str


@dataclass(frozen=True)
class FoodDominanceResult:
    retained: tuple[FoodOption, ...]
    pruned: tuple[FoodDominanceRecord, ...]


def _food_lifecycle(document: Mapping[str, object]) -> tuple[str, tuple[Mapping[str, object], ...]]:
    consumable_id = str(document.get("consumable_id", ""))
    transitions = document.get("transitions")
    if not isinstance(transitions, Mapping) or not transitions:
        raise DataUnavailableError(f"Food {consumable_id!r} has no transition graph")
    states = {str(state) for state in transitions}
    referenced = {
        str(transition["next_state"])
        for transition in transitions.values()
        if isinstance(transition, Mapping)
        and transition.get("next_state") is not None
        and str(transition.get("next_item_id", consumable_id)) == consumable_id
    }
    roots = states - referenced
    if len(roots) != 1:
        raise DataUnavailableError(f"Food {consumable_id!r} must have exactly one initial state")
    initial = next(iter(roots))
    lifecycle: list[Mapping[str, object]] = []
    state = initial
    seen: set[str] = set()
    while True:
        if state in seen:
            raise DataUnavailableError(f"Food {consumable_id!r} contains a transition loop")
        seen.add(state)
        transition = transitions.get(state)
        if not isinstance(transition, Mapping):
            raise DataUnavailableError(f"Food {consumable_id!r} lacks state {state!r}")
        lifecycle.append(transition)
        next_state = transition.get("next_state")
        if next_state is None:
            break
        if str(transition.get("next_item_id", consumable_id)) != consumable_id:
            raise DataUnavailableError(f"Food {consumable_id!r} changes item identity and cannot use simple dominance")
        state = str(next_state)
    return initial, tuple(lifecycle)


def _dominates(
    left_id: str,
    left: tuple[Mapping[str, object], ...],
    right_id: str,
    right: tuple[Mapping[str, object], ...],
    *,
    left_tiebreaker: tuple[int, str],
    right_tiebreaker: tuple[int, str],
) -> bool:
    if left_id == right_id or len(left) != len(right):
        return False
    strictly_better = False
    for left_step, right_step in zip(left, right):
        # Effects and byproducts can change combat state or inventory utility;
        # never infer dominance across them.
        if any(key in step for step in (left_step, right_step) for key in ("effect", "next_item_id")):
            return False
        left_heal = left_step.get("healing")
        right_heal = right_step.get("healing")
        left_eat = left_step.get("eat_delay_ticks")
        right_eat = right_step.get("eat_delay_ticks")
        left_attack = left_step.get("attack_delay_ticks")
        right_attack = right_step.get("attack_delay_ticks")
        if not all(
            isinstance(value, int) for value in (left_heal, right_heal, left_eat, right_eat, left_attack, right_attack)
        ):
            raise DataUnavailableError("Verified food dominance needs exact integer healing and timing")
        if left_heal < right_heal or left_eat > right_eat or left_attack > right_attack:
            return False
        strictly_better |= left_heal > right_heal or left_eat < right_eat or left_attack < right_attack
    # Strategically identical foods are one search state. Prefer the lowest
    # source-observed item ID so equivalent holiday rares do not displace an
    # ordinary food merely because its text ID sorts first.
    return strictly_better or left_tiebreaker < right_tiebreaker


def prune_dominated_foods(documents: Iterable[Mapping[str, object]]) -> FoodDominanceResult:
    foods = tuple(
        sorted(
            (
                document
                for document in documents
                if document.get("kind") == "food"
                and document.get("status") == "verified"
                and document.get("availability_scope") == F2P_STANDARD_WORLD_SCOPE
            ),
            key=lambda document: str(document.get("consumable_id", "")),
        )
    )
    parsed = {}
    for document in foods:
        consumable_id = str(document["consumable_id"])
        item_ids = document.get("item_ids")
        if not isinstance(item_ids, list) or not item_ids or not all(isinstance(item_id, int) for item_id in item_ids):
            raise DataUnavailableError(f"Food {consumable_id!r} has no exact item IDs")
        parsed[consumable_id] = (*_food_lifecycle(document), (min(item_ids), consumable_id))
    retained: list[FoodOption] = []
    pruned: list[FoodDominanceRecord] = []
    for candidate_id, (initial_state, candidate_lifecycle, candidate_tiebreaker) in parsed.items():
        dominators = [
            other_id
            for other_id, (_, other_lifecycle, other_tiebreaker) in parsed.items()
            if _dominates(
                other_id,
                other_lifecycle,
                candidate_id,
                candidate_lifecycle,
                left_tiebreaker=other_tiebreaker,
                right_tiebreaker=candidate_tiebreaker,
            )
        ]
        if not dominators:
            retained.append(FoodOption(candidate_id, initial_state))
            continue
        dominator = min(dominators, key=lambda item_id: parsed[item_id][2])
        pruned.append(
            FoodDominanceRecord(
                candidate_id,
                dominator,
                "same verified action count and no side effects; "
                "every heal/timer is weakly better and at least one is strictly better",
            )
        )
    return FoodDominanceResult(tuple(retained), tuple(pruned))
