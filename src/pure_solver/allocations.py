"""Inventory allocations for a combat kit: enumerate count-equivalent fills of the free slots from a set of
``InventoryOption`` items with the kit's switch slots reserved, never raw slot permutations.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import product

from .canonical import canonical_hash
from .inventory import InventoryEntry, InventoryState
from .kits import CombatKit, inventory_fits_combat_kit


@dataclass(frozen=True)
class InventoryOption:
    item_id: str
    initial_state: str
    minimum_count: int = 0
    maximum_count: int = 28
    stackable: bool = False

    def __post_init__(self) -> None:
        if self.minimum_count < 0 or self.maximum_count < self.minimum_count:
            raise ValueError("Inventory option has invalid count bounds")


@dataclass(frozen=True)
class InventoryAllocation:
    inventory: InventoryState
    reserved_switch_slots: int

    @property
    def total_slots_used(self) -> int:
        return self.inventory.occupied_slots + self.reserved_switch_slots

    @property
    def remaining_slots(self) -> int:
        return self.inventory.capacity - self.total_slots_used

    @property
    def canonical_id(self) -> str:
        return canonical_hash(
            {
                "inventory": self.inventory,
                "reserved_switch_slots": self.reserved_switch_slots,
            }
        )


def generate_inventory_allocations(
    kit: CombatKit,
    options: Iterable[InventoryOption],
    *,
    capacity: int = 28,
    fill_capacity: bool = False,
) -> tuple[InventoryAllocation, ...]:
    """Enumerate count-equivalent inventories, never raw slot permutations."""
    option_list = tuple(options)
    if len({option.item_id for option in option_list}) != len(option_list):
        raise ValueError("Inventory options must have unique item IDs")
    available = kit.available_inventory_slots(capacity)
    allocations: dict[str, InventoryAllocation] = {}
    ranges = [range(option.minimum_count, min(option.maximum_count, available) + 1) for option in option_list]
    for counts in product(*ranges):
        occupied = sum(1 if option.stackable and count > 0 else count for option, count in zip(option_list, counts))
        if occupied > available:
            continue
        entries = tuple(
            InventoryEntry(option.item_id, option.initial_state, count, option.stackable)
            for option, count in zip(option_list, counts)
            if count > 0
        )
        inventory = InventoryState(entries, capacity)
        if not inventory_fits_combat_kit(inventory, kit):
            continue
        allocation = InventoryAllocation(inventory, kit.inventory_slots)
        if fill_capacity and allocation.remaining_slots != 0:
            continue
        allocations[allocation.canonical_id] = allocation
    return tuple(sorted(allocations.values(), key=lambda allocation: allocation.canonical_id))
