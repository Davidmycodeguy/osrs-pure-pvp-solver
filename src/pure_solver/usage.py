"""Per-fight consumable usage measured against verified transition graphs (``FightResourceUsage``) and the
population summary across fights (``ResourceUsageSummary``).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .errors import DataUnavailableError, MechanicConflictError
from .inventory import InventoryEntry, InventoryState
from .legality import F2P_STANDARD_WORLD_SCOPE


def _maximum_actions_for_entry(
    entry: InventoryEntry,
    consumables: Mapping[str, Mapping[str, object]],
) -> int:
    definition = consumables.get(entry.item_id)
    if (
        definition is None
        or definition.get("status") != "verified"
        or definition.get("availability_scope") != F2P_STANDARD_WORLD_SCOPE
        or not definition.get("source_ids")
    ):
        raise DataUnavailableError(f"No verified consumable definition for {entry.item_id!r}")
    transitions = definition.get("transitions")
    if not isinstance(transitions, Mapping):
        raise DataUnavailableError(f"Consumable {entry.item_id!r} has no transition graph")
    state = entry.state
    visited: set[str] = set()
    actions = 0
    while True:
        if state in visited:
            raise MechanicConflictError(f"Consumable {entry.item_id!r} contains a transition loop")
        visited.add(state)
        transition = transitions.get(state)
        if not isinstance(transition, Mapping):
            raise DataUnavailableError(f"Consumable {entry.item_id!r} has no transition from {state!r}")
        actions += 1
        next_state = transition.get("next_state")
        next_item_id = str(transition.get("next_item_id", entry.item_id))
        if next_state is None or next_item_id != entry.item_id:
            break
        state = str(next_state)
    return actions * entry.quantity


@dataclass(frozen=True)
class FightResourceUsage:
    actions_used_by_item: Mapping[str, int]
    maximum_actions_by_item: Mapping[str, int]
    reached_maximum_by_item: Mapping[str, bool]
    remaining_units_by_item: Mapping[str, int]
    has_food: bool
    all_food_consumed: bool


def measure_fight_usage(
    initial: InventoryState,
    final: InventoryState,
    consumed_items: Iterable[str],
    consumables: Mapping[str, Mapping[str, object]],
) -> FightResourceUsage:
    maximum: Counter[str] = Counter()
    starting_food_ids: set[str] = set()
    for entry in initial.entries:
        if entry.item_id in consumables:
            if consumables[entry.item_id].get("kind") == "food":
                starting_food_ids.add(entry.item_id)
            maximum[entry.item_id] += _maximum_actions_for_entry(entry, consumables)
    used = Counter(item_id for item_id in consumed_items if item_id in consumables)
    remaining = Counter()
    for entry in final.entries:
        if entry.item_id in starting_food_ids:
            remaining[entry.item_id] += entry.quantity
    overused = {
        item_id: (used[item_id], maximum_actions)
        for item_id, maximum_actions in maximum.items()
        if used[item_id] > maximum_actions
    }
    if overused:
        raise MechanicConflictError(f"Fight consumed more uses than the starting inventory allowed: {overused}")
    return FightResourceUsage(
        actions_used_by_item=dict(sorted(used.items())),
        maximum_actions_by_item=dict(sorted(maximum.items())),
        reached_maximum_by_item={
            item_id: used[item_id] == maximum_actions for item_id, maximum_actions in sorted(maximum.items())
        },
        remaining_units_by_item={item_id: remaining[item_id] for item_id in sorted(starting_food_ids)},
        has_food=bool(starting_food_ids),
        all_food_consumed=bool(starting_food_ids) and all(remaining[item_id] == 0 for item_id in starting_food_ids),
    )


@dataclass(frozen=True)
class ResourceUsageSummary:
    fights: int
    usage_histogram_by_item: Mapping[str, Mapping[int, int]]
    mean_actions_used_by_item: Mapping[str, float]
    maximum_observed_actions_by_item: Mapping[str, int]
    maximum_possible_actions_by_item: Mapping[str, int]
    reached_maximum_fights_by_item: Mapping[str, int]
    reached_maximum_rate_by_item: Mapping[str, float]
    fights_with_food: int
    all_food_consumed_fights: int
    all_food_consumed_rate: float | None


def summarise_resource_usage(fights: Iterable[FightResourceUsage]) -> ResourceUsageSummary:
    records = tuple(fights)
    if not records:
        raise ValueError("Resource summary requires at least one fight")
    item_ids = sorted({item_id for record in records for item_id in record.maximum_actions_by_item})
    histograms: dict[str, dict[int, int]] = {}
    means: dict[str, float] = {}
    observed_maximum: dict[str, int] = {}
    possible_maximum: dict[str, int] = {}
    reached_counts: dict[str, int] = {}
    reached_rates: dict[str, float] = {}
    for item_id in item_ids:
        histogram = Counter(record.actions_used_by_item.get(item_id, 0) for record in records)
        possible_values = {record.maximum_actions_by_item.get(item_id, 0) for record in records}
        # Different starting inventories should be reported separately instead
        # of pretending they share one maximum-use denominator.
        if len(possible_values) != 1:
            raise MechanicConflictError(
                f"Cannot aggregate {item_id!r}: fights have different maximum possible uses {sorted(possible_values)}"
            )
        possible = next(iter(possible_values))
        reached = sum(record.reached_maximum_by_item.get(item_id, False) for record in records)
        histograms[item_id] = dict(sorted(histogram.items()))
        means[item_id] = sum(uses * count for uses, count in histogram.items()) / len(records)
        observed_maximum[item_id] = max(histogram)
        possible_maximum[item_id] = possible
        reached_counts[item_id] = reached
        reached_rates[item_id] = reached / len(records)
    fights_with_food = sum(record.has_food for record in records)
    all_food = sum(record.all_food_consumed for record in records)
    return ResourceUsageSummary(
        fights=len(records),
        usage_histogram_by_item=histograms,
        mean_actions_used_by_item=means,
        maximum_observed_actions_by_item=observed_maximum,
        maximum_possible_actions_by_item=possible_maximum,
        reached_maximum_fights_by_item=reached_counts,
        reached_maximum_rate_by_item=reached_rates,
        fights_with_food=fights_with_food,
        all_food_consumed_fights=all_food,
        all_food_consumed_rate=all_food / fights_with_food if fights_with_food else None,
    )
