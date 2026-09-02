"""Exact combat-level account profiles for 1-Defence F2P pures.

The legacy gear-band pipeline gave every representative a placeholder 10
Hitpoints. This module instead enumerates accounts whose combat level is
*exactly* the target, whose Hitpoints are reachable through ordinary F2P
combat training, and whose Prayer sits on a verified prayer breakpoint. Magic
is filled to the highest level that keeps the combat level unchanged.

Ported to Rust as ``pure_math/src/account_frontier.rs``; this module is the golden reference.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountState
from .errors import DataUnavailableError
from .experience import standard_f2p_hitpoints_levels
from .legality import EquipmentItem, is_item_legal
from .mechanics import MechanicRegistry
from .prayers import relevant_prayer_levels

PINNED_COMBAT_FORMULA = "osrs-wiki-combat-level-15305725"
LEVEL_FIELDS = ("attack", "strength", "ranged", "magic", "prayer", "hitpoints")
MINIMUM_HITPOINTS = 10
MAXIMUM_LEVEL = 99
_DEFENCE = 1

# Integer form of the pinned formula: combat = floor(numerator / 160) where
# numerator = 40 * (defence + hitpoints + prayer // 2) + 52 * dominant.
_HP_PRAYER_WEIGHT = 40
_DOMINANT_WEIGHT = 52
_COMBAT_DENOMINATOR = 160


@dataclass(frozen=True)
class AccountFrontier:
    combat_level: int
    prayer_levels: tuple[int, ...]
    raw_count: int
    full_frontier: tuple[AccountState, ...]
    ranking_frontier: tuple[AccountState, ...]

    def to_document(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "purpose": "exact_combat_level_account_frontier",
            "combat_level": self.combat_level,
            "defence_level": _DEFENCE,
            "hitpoints_model": "standard_f2p_training_reachable_range",
            "magic_model": "maximum_level_preserving_combat_level",
            "prayer_levels": list(self.prayer_levels),
            "counts": {
                "raw_legal_states": self.raw_count,
                "full_frontier": len(self.full_frontier),
                "ranking_frontier": len(self.ranking_frontier),
            },
            "ranking_frontier_scope": (
                "Pareto over Attack/Strength/Ranged/Prayer/Hitpoints; Magic treated as leftover fill"
            ),
            "full_frontier_scope": "Pareto over all six trainable skills; Magic preserved as a dimension",
        }


def _require_pinned_formula(mechanics: MechanicRegistry) -> None:
    mechanic = mechanics.require("combat_level")
    if mechanic.formula_version != PINNED_COMBAT_FORMULA:
        raise DataUnavailableError(
            f"Account frontier requires combat formula {PINNED_COMBAT_FORMULA!r}, got {mechanic.formula_version!r}"
        )


def prayer_level_choices(mechanics: MechanicRegistry) -> tuple[int, ...]:
    """Verified prayer breakpoints, lifted to the odd level that costs the same combat.

    Combat level only counts ``prayer // 2``, so the odd level directly above an
    even breakpoint is free and strictly better.
    """
    breakpoints = relevant_prayer_levels(mechanics, include_protection=True)
    lifted = {level if level % 2 else min(level + 1, MAXIMUM_LEVEL) for level in breakpoints}
    return tuple(sorted(lifted))


def _dominant(attack: int, strength: int, ranged: int, magic: int) -> int:
    return max(attack + strength, (ranged * 3) // 2, (magic * 3) // 2)


def _combat_numerator(hitpoints: int, prayer: int, dominant: int) -> int:
    return _HP_PRAYER_WEIGHT * (_DEFENCE + hitpoints + prayer // 2) + _DOMINANT_WEIGHT * dominant


def maximum_magic_for_combat(
    *, attack: int, strength: int, ranged: int, prayer: int, hitpoints: int, combat_level: int
) -> int | None:
    """Highest Magic level keeping the combat level exact, or None if unreachable."""
    low = _COMBAT_DENOMINATOR * combat_level
    high = _COMBAT_DENOMINATOR * (combat_level + 1) - 1
    best: int | None = None
    for magic in range(1, MAXIMUM_LEVEL + 1):
        numerator = _combat_numerator(hitpoints, prayer, _dominant(attack, strength, ranged, magic))
        if numerator > high:
            break
        if numerator >= low:
            best = magic
    return best


def _melee_ranged_triples(combat_level: int) -> Iterator[tuple[int, int, int]]:
    """Attack/Strength/Ranged triples that can still fit under the combat ceiling."""
    high = _COMBAT_DENOMINATOR * (combat_level + 1) - 1
    floor_cost = _HP_PRAYER_WEIGHT * (_DEFENCE + MINIMUM_HITPOINTS)
    for attack in range(1, MAXIMUM_LEVEL + 1):
        for strength in range(1, MAXIMUM_LEVEL + 1):
            if _DOMINANT_WEIGHT * (attack + strength) + floor_cost > high:
                break
            for ranged in range(1, MAXIMUM_LEVEL + 1):
                if _DOMINANT_WEIGHT * _dominant(attack, strength, ranged, 1) + floor_cost > high:
                    break
                yield attack, strength, ranged


def enumerate_exact_combat_accounts(
    mechanics: MechanicRegistry,
    *,
    combat_level: int,
    prayer_levels: Sequence[int] | None = None,
) -> Iterator[AccountState]:
    """Yield every Magic-max-filled account at exactly ``combat_level``.

    Every yielded account is re-checked against the authoritative
    ``AccountState.combat_level`` so a drift in the pinned formula fails closed.
    """
    _require_pinned_formula(mechanics)
    prayers = tuple(prayer_levels) if prayer_levels is not None else prayer_level_choices(mechanics)
    for attack, strength, ranged in _melee_ranged_triples(combat_level):
        hitpoints_levels = standard_f2p_hitpoints_levels(
            attack_level=attack, strength_level=strength, ranged_level=ranged, mechanics=mechanics
        )
        for prayer in prayers:
            for hitpoints in hitpoints_levels:
                magic = maximum_magic_for_combat(
                    attack=attack,
                    strength=strength,
                    ranged=ranged,
                    prayer=prayer,
                    hitpoints=hitpoints,
                    combat_level=combat_level,
                )
                if magic is None:
                    continue
                yield _verified_account(mechanics, attack, strength, ranged, magic, prayer, hitpoints, combat_level)


def _verified_account(
    mechanics: MechanicRegistry,
    attack: int,
    strength: int,
    ranged: int,
    magic: int,
    prayer: int,
    hitpoints: int,
    combat_level: int,
) -> AccountState:
    account = AccountState(attack, strength, ranged, magic, prayer, hitpoints)
    if account.combat_level(mechanics) != combat_level:
        raise DataUnavailableError("Compiled combat arithmetic disagrees with the verified combat-level formula")
    return account


def account_levels(account: AccountState) -> tuple[int, int, int, int, int, int]:
    return tuple(getattr(account, f"{field}_level") for field in LEVEL_FIELDS)  # type: ignore[return-value]


def pareto_frontier(
    accounts: Iterable[AccountState],
    *,
    ignore_magic: bool,
) -> tuple[AccountState, ...]:
    """Drop accounts that another account matches or beats in every compared skill.

    Because Magic is always max-filled, an account can only be dominated by one
    with the *same* Magic when Magic counts, so Magic acts as a group key. When
    Magic is ignored it is simply not compared.
    """
    compared = (0, 1, 2, 4, 5)
    grouping = () if ignore_magic else (3,)
    groups: dict[tuple[int, ...], list[tuple[tuple[int, ...], AccountState]]] = defaultdict(list)
    key_indices = tuple(index for index in range(5) if index in compared or index in grouping)
    for levels, account in _highest_hitpoints_only(accounts, key_indices).items():
        groups[tuple(levels[index] for index in grouping)].append((levels, account))
    survivors: list[AccountState] = []
    for members in groups.values():
        survivors.extend(_group_frontier(members, compared))
    return tuple(sorted(survivors, key=account_levels))


def _highest_hitpoints_only(
    accounts: Iterable[AccountState],
    key_indices: tuple[int, ...],
) -> dict[tuple[int, ...], AccountState]:
    """Cheap pre-pass: with every other level equal, only the highest HP can survive."""
    best: dict[tuple[int, ...], tuple[tuple[int, ...], AccountState]] = {}
    for account in accounts:
        levels = account_levels(account)
        key = tuple(levels[index] for index in key_indices)
        current = best.get(key)
        if current is None or levels[5] > current[0][5]:
            best[key] = (levels, account)
    return {levels: account for levels, account in best.values()}


def _group_frontier(
    members: list[tuple[tuple[int, ...], AccountState]],
    compared: tuple[int, ...],
) -> list[AccountState]:
    members.sort(key=lambda entry: -sum(entry[0][index] for index in compared))
    kept_levels: list[tuple[int, ...]] = []
    kept: list[AccountState] = []
    for levels, account in members:
        if any(all(other[index] >= levels[index] for index in compared) for other in kept_levels):
            continue
        kept_levels.append(levels)
        kept.append(account)
    return kept


def build_account_frontier(mechanics: MechanicRegistry, *, combat_level: int = 30) -> AccountFrontier:
    prayers = prayer_level_choices(mechanics)
    raw = tuple(enumerate_exact_combat_accounts(mechanics, combat_level=combat_level, prayer_levels=prayers))
    if not raw:
        raise DataUnavailableError(f"No 1-Defence account reaches combat level {combat_level} exactly")
    return AccountFrontier(
        combat_level=combat_level,
        prayer_levels=prayers,
        raw_count=len(raw),
        full_frontier=pareto_frontier(raw, ignore_magic=False),
        ranking_frontier=pareto_frontier(raw, ignore_magic=True),
    )


def equipment_unlock_signature(account: AccountState, items: Iterable[EquipmentItem]) -> frozenset[int]:
    """The set of verified item IDs this account may equip; equal sets share gear."""
    return frozenset(item.item_id for item in items if is_item_legal(item, account))


def write_account_frontier_csv(
    accounts: Iterable[AccountState], mechanics: MechanicRegistry, output: str | Path
) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([*LEVEL_FIELDS, "defence", "combat_level"])
        for account in accounts:
            writer.writerow([*account_levels(account), account.defence_level, account.combat_level(mechanics)])


def write_account_frontier_json(frontier: AccountFrontier, output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(frontier.to_document(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def top_ranked_accounts(ranked_csv: str | Path, *, limit: int) -> tuple[AccountState, ...]:
    """Distinct accounts behind the best-ranked rows, in first-appearance order."""
    seen: dict[tuple[int, ...], AccountState] = {}
    with Path(ranked_csv).open(newline="", encoding="utf-8") as handle:
        rows = sorted(csv.DictReader(handle), key=lambda row: int(row["rank"]))
    for row in rows:
        levels = tuple(int(row[f"account_{field}"]) for field in LEVEL_FIELDS)
        if levels not in seen:
            seen[levels] = AccountState(*levels)
        if len(seen) == limit:
            break
    return tuple(seen.values())


def read_account_frontier_csv(path: str | Path) -> tuple[AccountState, ...]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = set(LEVEL_FIELDS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Account frontier CSV is missing columns: {', '.join(sorted(missing))}")
        return tuple(AccountState(*(int(row[field]) for field in LEVEL_FIELDS)) for row in reader)
