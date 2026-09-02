"""Strict per-account item dominance: an item is pruned only when a legal item with the same mechanic signature
matches or beats every bonus (weight minimised), and every removal is recorded.

Ported to Rust as ``pure_math/src/dominance.rs``; this module is the golden reference.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .accounts import AccountState
from .legality import EquipmentItem, LegalityContext, is_item_legal

_MINIMISE_BONUSES = {"weight"}


@dataclass(frozen=True)
class DominanceRecord:
    dominated_item_id: int
    dominating_item_id: int
    account_id: str
    reason: str


@dataclass(frozen=True)
class DominanceResult:
    retained: tuple[EquipmentItem, ...]
    rejected_illegal: tuple[EquipmentItem, ...]
    pruned: tuple[DominanceRecord, ...]


def _mechanic_signature(item: EquipmentItem) -> tuple[object, ...]:
    """Properties that must match before numerical dominance is meaningful."""
    return (
        item.slot,
        item.weapon_type,
        item.two_handed,
        tuple(sorted(item.attack_styles)),
        tuple(sorted(item.ammo_ids)),
        tuple(sorted(item.spell_ids)),
        tuple(sorted(item.mechanic_flags)),
    )


def _bonus_comparison(dominator: EquipmentItem, candidate: EquipmentItem) -> tuple[bool, bool]:
    all_keys = set(dominator.bonuses) | set(candidate.bonuses)
    weakly_better = True
    strictly_better = False
    for key in all_keys:
        left = dominator.bonuses.get(key, 0)
        right = candidate.bonuses.get(key, 0)
        if key in _MINIMISE_BONUSES:
            weakly_better &= left <= right
            strictly_better |= left < right
        else:
            weakly_better &= left >= right
            strictly_better |= left > right
    return weakly_better, strictly_better


def dominates_for_account(
    dominator: EquipmentItem,
    candidate: EquipmentItem,
    account: AccountState,
    context: LegalityContext = LegalityContext(),
    *,
    ammo_compatibility: Mapping[int, frozenset[int]] | None = None,
) -> bool:
    """Return whether one legal item can safely remove another for this account.

    This is intentionally stricter than a DPS comparison. Mechanic signatures
    must be identical, every numeric bonus must be no worse, weapon speed must
    be no slower, and range must be no shorter. Distinct KO behaviour, ammo,
    spell compatibility, handedness, or special flags prevents pruning.
    """
    if dominator.item_id == candidate.item_id:
        return False
    if not is_item_legal(dominator, account, context) or not is_item_legal(candidate, account, context):
        return False
    if _mechanic_signature(dominator) != _mechanic_signature(candidate):
        return False
    if dominator.slot == "ammo" and (
        ammo_compatibility is None
        or ammo_compatibility.get(dominator.item_id, frozenset())
        != ammo_compatibility.get(candidate.item_id, frozenset())
    ):
        # Ammunition carries no reverse link to compatible weapons. Without a
        # catalog-derived compatibility signature, arrows and bolts can look
        # numerically comparable even though they are not interchangeable.
        return False
    weakly_better, strictly_better = _bonus_comparison(dominator, candidate)
    if not weakly_better:
        return False

    if candidate.attack_speed is not None:
        if dominator.attack_speed is None or dominator.attack_speed > candidate.attack_speed:
            return False
        strictly_better |= dominator.attack_speed < candidate.attack_speed
    elif dominator.attack_speed is not None:
        # Missing timing data is not interpreted as infinitely slow or fast.
        return False

    if candidate.attack_range is not None:
        if dominator.attack_range is None or dominator.attack_range < candidate.attack_range:
            return False
        strictly_better |= dominator.attack_range > candidate.attack_range
    elif dominator.attack_range is not None:
        return False

    # Identical mechanics and numbers are equivalent. Keep one canonical item
    # instead of multiplying loadouts by cosmetic/name variants.
    if not strictly_better:
        return dominator.item_id < candidate.item_id
    return True


def prune_dominated_items(
    account: AccountState,
    items: Iterable[EquipmentItem],
    *,
    context: LegalityContext = LegalityContext(),
) -> DominanceResult:
    legal: list[EquipmentItem] = []
    illegal: list[EquipmentItem] = []
    for item in items:
        (legal if is_item_legal(item, account, context) else illegal).append(item)
    legal.sort(key=lambda item: item.item_id)
    ammo_compatibility: dict[int, set[int]] = {}
    for weapon in legal:
        for ammo_id in weapon.ammo_ids:
            ammo_compatibility.setdefault(ammo_id, set()).add(weapon.item_id)
    frozen_ammo_compatibility = {ammo_id: frozenset(weapon_ids) for ammo_id, weapon_ids in ammo_compatibility.items()}

    retained: list[EquipmentItem] = []
    records: list[DominanceRecord] = []
    for candidate in legal:
        dominators = [
            item
            for item in legal
            if dominates_for_account(
                item,
                candidate,
                account,
                context,
                ammo_compatibility=frozen_ammo_compatibility,
            )
        ]
        if not dominators:
            retained.append(candidate)
            continue
        # Choose a deterministic audit representative. There may be several
        # transitive dominators; keeping the lowest ID makes snapshots stable.
        dominator = min(dominators, key=lambda item: item.item_id)
        records.append(
            DominanceRecord(
                dominated_item_id=candidate.item_id,
                dominating_item_id=dominator.item_id,
                account_id=account.canonical_id,
                reason=(
                    "same verified mechanic signature; all relevant bonuses are weakly better; "
                    "attack speed/range are weakly better; at least one dimension is strictly better "
                    "or the records are strategically equivalent"
                ),
            )
        )
    return DominanceResult(tuple(retained), tuple(illegal), tuple(records))
