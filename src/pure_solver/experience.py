"""Experience-table mechanics: XP for level, the damage range ordinary F2P combat training implies, the Hitpoints
levels that training can reach for given Attack/Strength/Ranged, and historical training proofs.

The parts used by the ranking path are ported to Rust as ``pure_math/src/experience.rs``; this module is the
golden reference.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache

from .accounts import AccountSearchBounds, AccountState, LevelRange, enumerate_account_states
from .errors import DataUnavailableError, LegalityError, SearchBudgetExceeded
from .mechanics import MechanicRegistry

COMBAT_SKILLS = ("attack", "strength", "ranged", "magic", "prayer", "hitpoints", "defence")


@lru_cache(maxsize=512)
def _xp_for_level_formula(level: int, formula_version: str) -> int:
    del formula_version  # Version remains part of the cache key and provenance boundary.
    points = sum(math.floor(current + 300 * (2 ** (current / 7))) for current in range(1, level))
    return points // 4


def xp_for_level(level: int, mechanics: MechanicRegistry) -> int:
    mechanic = mechanics.require("experience.level_threshold")
    if not 1 <= level <= 99:
        raise ValueError("XP level must be between 1 and 99")
    return _xp_for_level_formula(level, mechanic.formula_version)


def level_for_xp(xp: int | Fraction, mechanics: MechanicRegistry) -> int:
    mechanics.require("experience.level_threshold")
    if xp < 0:
        raise ValueError("XP cannot be negative")
    for level in range(99, 0, -1):
        if xp >= xp_for_level(level, mechanics):
            return level
    return 1


def _ceil_fraction(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def _standard_damage_range_for_level(level: int, mechanics: MechanicRegistry) -> tuple[int, int]:
    minimum_xp = xp_for_level(level, mechanics)
    maximum_xp = xp_for_level(level + 1, mechanics) - 1 if level < 99 else 200_000_000
    return _ceil_fraction(Fraction(minimum_xp, 4)), maximum_xp // 4


def standard_f2p_damage_range(account: AccountState, mechanics: MechanicRegistry) -> tuple[int, int]:
    """Damage required when Attack/Strength/Ranged are trained through normal F2P combat."""
    return standard_f2p_damage_range_for_levels(
        account.attack_level,
        account.strength_level,
        account.ranged_level,
        mechanics,
    )


def standard_f2p_damage_range_for_levels(
    attack_level: int,
    strength_level: int,
    ranged_level: int,
    mechanics: MechanicRegistry,
) -> tuple[int, int]:
    ranges = (
        _standard_damage_range_for_level(attack_level, mechanics),
        _standard_damage_range_for_level(strength_level, mechanics),
        _standard_damage_range_for_level(ranged_level, mechanics),
    )
    return sum(item[0] for item in ranges), sum(item[1] for item in ranges)


def minimum_standard_f2p_hitpoints_level(
    account: AccountState,
    mechanics: MechanicRegistry,
) -> int:
    minimum_damage, _ = standard_f2p_damage_range(account, mechanics)
    starting_hp_xp = xp_for_level(10, mechanics)
    hp_xp = Fraction(starting_hp_xp) + Fraction(4 * minimum_damage, 3)
    return level_for_xp(hp_xp, mechanics)


def standard_f2p_hitpoints_achievable(
    account: AccountState,
    mechanics: MechanicRegistry,
) -> bool:
    """Whether ordinary F2P combat XP ranges overlap the requested HP level.

    Magic is excluded because it can be trained without HP through splashing,
    curses, teleports, enchanting, and alchemy. Quest XP, dummies, lamps,
    members training, and cannoning belong to separate training-history modes.
    """
    if account.hitpoints_level < 10:
        return False
    damage_min, damage_max = standard_f2p_damage_range(account, mechanics)
    starting_hp_xp = xp_for_level(10, mechanics)
    hp_min = xp_for_level(account.hitpoints_level, mechanics)
    hp_max = xp_for_level(account.hitpoints_level + 1, mechanics) - 1 if account.hitpoints_level < 99 else 200_000_000
    hp_damage_min = max(0, _ceil_fraction(Fraction(3 * (hp_min - starting_hp_xp), 4)))
    maximum_damage_for_hp = Fraction(3 * (hp_max - starting_hp_xp), 4)
    hp_damage_max = max(0, maximum_damage_for_hp.numerator // maximum_damage_for_hp.denominator)
    return max(damage_min, hp_damage_min) <= min(damage_max, hp_damage_max)


def combat_level_hitpoints_interval(
    account: AccountState,
    mechanics: MechanicRegistry,
    *,
    combat_minimum: int,
    combat_maximum: int,
) -> tuple[int, int] | None:
    """Solve the pinned combat formula for HP instead of trying HP 1..99."""
    mechanic = mechanics.require("combat_level")
    if mechanic.formula_version != "osrs-wiki-combat-level-15305725":
        return None
    dominant = max(
        account.attack_level + account.strength_level,
        (account.ranged_level * 3) // 2,
        (account.magic_level * 3) // 2,
    )
    fixed_numerator = 40 * (account.defence_level + account.prayer_level // 2) + 52 * dominant
    minimum_hp = _ceil_fraction(Fraction(160 * combat_minimum - fixed_numerator, 40))
    maximum_hp = (160 * combat_maximum + 159 - fixed_numerator) // 40
    minimum_hp = max(1, minimum_hp)
    maximum_hp = min(99, maximum_hp)
    if minimum_hp > maximum_hp:
        return None
    return minimum_hp, maximum_hp


def standard_f2p_hitpoints_levels(
    *,
    attack_level: int,
    strength_level: int,
    ranged_level: int,
    mechanics: MechanicRegistry,
    requested: LevelRange = LevelRange(10, 99),
) -> tuple[int, ...]:
    """Return only HP levels whose XP interval overlaps ordinary-combat damage."""
    damage_min, damage_max = standard_f2p_damage_range_for_levels(attack_level, strength_level, ranged_level, mechanics)
    starting_hp_xp = xp_for_level(10, mechanics)
    lowest = level_for_xp(Fraction(starting_hp_xp) + Fraction(4 * damage_min, 3), mechanics)
    highest = level_for_xp(Fraction(starting_hp_xp) + Fraction(4 * damage_max, 3), mechanics)
    result: list[int] = []
    for hitpoints in range(max(10, requested.minimum, lowest), min(requested.maximum, highest) + 1):
        probe = AccountState(attack_level, strength_level, ranged_level, 1, 1, hitpoints)
        if standard_f2p_hitpoints_achievable(probe, mechanics):
            result.append(hitpoints)
    return tuple(result)


def enumerate_standard_f2p_account_states(
    bounds: AccountSearchBounds,
    mechanics: MechanicRegistry,
    *,
    max_candidates: int | None = None,
) -> Iterator[AccountState]:
    """Yield only accounts in the combat and standard-training HP intersection."""
    mechanic = mechanics.require("combat_level")
    if mechanic.formula_version != "osrs-wiki-combat-level-15305725":
        yielded = 0
        for account in enumerate_account_states(bounds, mechanics):
            if not standard_f2p_hitpoints_achievable(account, mechanics):
                continue
            if max_candidates is not None and yielded >= max_candidates:
                raise SearchBudgetExceeded(
                    f"Account search reached its explicit {max_candidates}-candidate budget; result is not exhaustive."
                )
            yielded += 1
            yield account
        return

    yielded = 0
    for attack in bounds.attack.values():
        for strength in bounds.strength.values():
            for ranged in bounds.ranged.values():
                training_hitpoints = standard_f2p_hitpoints_levels(
                    attack_level=attack,
                    strength_level=strength,
                    ranged_level=ranged,
                    mechanics=mechanics,
                    requested=bounds.hitpoints,
                )
                if not training_hitpoints:
                    continue
                for magic in bounds.magic.values():
                    for prayer in bounds.prayer.values():
                        probe = AccountState(attack, strength, ranged, magic, prayer, training_hitpoints[0])
                        combat_interval = combat_level_hitpoints_interval(
                            probe,
                            mechanics,
                            combat_minimum=bounds.combat_minimum,
                            combat_maximum=bounds.combat_maximum,
                        )
                        if combat_interval is None:
                            continue
                        combat_hp_min, combat_hp_max = combat_interval
                        for hitpoints in training_hitpoints:
                            if not combat_hp_min <= hitpoints <= combat_hp_max:
                                continue
                            account = AccountState(attack, strength, ranged, magic, prayer, hitpoints)
                            if not bounds.combat_minimum <= account.combat_level(mechanics) <= bounds.combat_maximum:
                                raise DataUnavailableError(
                                    "Direct HP interval disagrees with the verified combat-level formula"
                                )
                            if max_candidates is not None and yielded >= max_candidates:
                                raise SearchBudgetExceeded(
                                    f"Account search reached its explicit {max_candidates}-candidate budget; "
                                    "result is not exhaustive."
                                )
                            yielded += 1
                            yield account


@dataclass(frozen=True)
class TrainingEvent:
    event_id: str
    repetitions: int
    xp_per_repetition: Mapping[str, Fraction]
    tags: frozenset[str]
    source_ids: tuple[str, ...]
    status: str = "unverified"

    def validate(self, mechanics: MechanicRegistry) -> None:
        if self.status != "verified" or not self.source_ids:
            raise DataUnavailableError(f"Training event {self.event_id!r} is not verified")
        if self.repetitions < 0:
            raise ValueError("Training repetitions cannot be negative")
        unknown_skills = set(self.xp_per_repetition) - set(COMBAT_SKILLS)
        if unknown_skills or any(value < 0 for value in self.xp_per_repetition.values()):
            raise DataUnavailableError(
                f"Training event {self.event_id!r} has invalid XP fields: {sorted(unknown_skills)}"
            )
        unavailable_sources = set(self.source_ids) - set(mechanics.source_revisions)
        if unavailable_sources:
            raise DataUnavailableError(
                f"Training event {self.event_id!r} cites unavailable sources: {sorted(unavailable_sources)}"
            )


@dataclass(frozen=True)
class AchievabilityRules:
    forbidden_tags: frozenset[str] = frozenset()


@dataclass(frozen=True)
class HistoricalAccountProof:
    initial_xp: Mapping[str, Fraction]
    events: tuple[TrainingEvent, ...]

    def final_xp(
        self,
        mechanics: MechanicRegistry,
        rules: AchievabilityRules = AchievabilityRules(),
    ) -> Mapping[str, Fraction]:
        missing = set(COMBAT_SKILLS) - set(self.initial_xp)
        if missing:
            raise DataUnavailableError(f"Training proof lacks initial XP for {sorted(missing)}")
        totals = {skill: Fraction(self.initial_xp[skill]) for skill in COMBAT_SKILLS}
        for event in self.events:
            event.validate(mechanics)
            prohibited = event.tags & rules.forbidden_tags
            if prohibited:
                raise LegalityError(f"Training event {event.event_id!r} violates restrictions: {sorted(prohibited)}")
            for skill, amount in event.xp_per_repetition.items():
                totals[skill] += amount * event.repetitions
        return totals

    def proves(
        self,
        account: AccountState,
        mechanics: MechanicRegistry,
        rules: AchievabilityRules = AchievabilityRules(),
    ) -> bool:
        totals = self.final_xp(mechanics, rules)
        expected = {
            "attack": account.attack_level,
            "strength": account.strength_level,
            "ranged": account.ranged_level,
            "magic": account.magic_level,
            "prayer": account.prayer_level,
            "hitpoints": account.hitpoints_level,
            "defence": account.defence_level,
        }
        return all(level_for_xp(totals[skill], mechanics) == level for skill, level in expected.items())
