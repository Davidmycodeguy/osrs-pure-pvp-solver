"""Immutable inventory model: ``InventoryEntry`` items in a named state and ``InventoryState`` with slot
accounting, canonical IDs and data-defined ``consume`` transitions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .canonical import canonical_hash
from .errors import DataUnavailableError, VerifiedMechanicMissingError
from .legality import F2P_STANDARD_WORLD_SCOPE


@dataclass(frozen=True, order=True)
class InventoryEntry:
    item_id: str
    state: str
    quantity: int = 1
    stackable: bool = False

    def __post_init__(self) -> None:
        if self.quantity < 1:
            raise ValueError("Inventory quantity must be positive")


@dataclass(frozen=True)
class InventoryState:
    entries: tuple[InventoryEntry, ...]
    capacity: int = 28

    def __post_init__(self) -> None:
        canonical = tuple(sorted(self.entries))
        if canonical != self.entries:
            object.__setattr__(self, "entries", canonical)
        if self.capacity < 0:
            raise ValueError("Inventory capacity cannot be negative")
        if self.occupied_slots > self.capacity:
            raise ValueError(f"Inventory occupies {self.occupied_slots} slots but capacity is {self.capacity}")

    @property
    def occupied_slots(self) -> int:
        return sum(1 if entry.stackable else entry.quantity for entry in self.entries)

    @property
    def remaining_slots(self) -> int:
        return self.capacity - self.occupied_slots

    @property
    def canonical_id(self) -> str:
        return canonical_hash(self)

    def consume(
        self, item_id: str, consumables: Mapping[str, Mapping[str, object]]
    ) -> tuple[InventoryState, Mapping[str, object]]:
        """Apply a verified data-defined item state transition.

        A pizza's first and second bites are different states; the simulator
        never reduces them to aggregate healing-per-slot.
        """
        definition = consumables.get(item_id)
        if definition is None:
            raise DataUnavailableError(f"Consumable {item_id!r} is absent from the immutable snapshot")
        if (
            definition.get("status") != "verified"
            or definition.get("availability_scope") != F2P_STANDARD_WORLD_SCOPE
            or not definition.get("source_ids")
        ):
            raise VerifiedMechanicMissingError(f"Consumable {item_id!r} is not verified")
        for index, entry in enumerate(self.entries):
            if entry.item_id != item_id:
                continue
            transitions = definition.get("transitions", {})
            transition = transitions.get(entry.state)
            if not isinstance(transition, Mapping):
                raise DataUnavailableError(f"Consumable {item_id!r} has no transition from state {entry.state!r}")
            next_entries = list(self.entries)
            if entry.quantity == 1:
                next_entries.pop(index)
            else:
                next_entries[index] = InventoryEntry(entry.item_id, entry.state, entry.quantity - 1, entry.stackable)
            next_state = transition.get("next_state")
            if next_state:
                next_item_id = str(transition.get("next_item_id", item_id))
                next_entries.append(InventoryEntry(next_item_id, str(next_state), stackable=entry.stackable))
            return InventoryState(tuple(next_entries), self.capacity), transition
        raise DataUnavailableError(f"Inventory has no {item_id!r} to consume")
