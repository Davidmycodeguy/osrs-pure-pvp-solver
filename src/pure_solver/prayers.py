"""Best verified prayer boost sets for the closed-form pipeline: melee attack/strength, ranged and protection
prayers chosen from the ``prayer.f2p.*`` boost tables for a prayer level, plus the prayer levels worth
searching.

Distinct from :mod:`pure_solver.prayer_book`, which models the full catalogue with drain and conflicts for
simulation. Ported to Rust as ``pure_math/src/prayers.rs``; this module is the golden reference.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from .errors import DataUnavailableError
from .mechanics import MechanicRegistry


def _fraction(value: object, label: str) -> Fraction:
    if isinstance(value, int):
        return Fraction(value, 1)
    if isinstance(value, Mapping):
        numerator = value.get("numerator")
        denominator = value.get("denominator")
        if isinstance(numerator, int) and isinstance(denominator, int) and denominator > 0:
            return Fraction(numerator, denominator)
    raise DataUnavailableError(f"{label} does not encode an exact fraction")


def _int(value: object, label: str) -> int:
    if not isinstance(value, int):
        raise DataUnavailableError(f"{label} is not an exact integer")
    return value


@dataclass(frozen=True)
class PrayerBoost:
    prayer_id: str
    level: int
    multiplier: Fraction


@dataclass(frozen=True)
class MeleePrayerSet:
    attack: PrayerBoost | None
    strength: PrayerBoost | None

    @property
    def attack_multiplier(self) -> Fraction:
        return self.attack.multiplier if self.attack else Fraction(1)

    @property
    def strength_multiplier(self) -> Fraction:
        return self.strength.multiplier if self.strength else Fraction(1)

    @property
    def prayer_ids(self) -> tuple[str, ...]:
        return tuple(prayer.prayer_id for prayer in (self.attack, self.strength) if prayer is not None)


@dataclass(frozen=True)
class RangedPrayerSet:
    offensive: PrayerBoost | None

    @property
    def multiplier(self) -> Fraction:
        return self.offensive.multiplier if self.offensive else Fraction(1)

    @property
    def prayer_ids(self) -> tuple[str, ...]:
        return (self.offensive.prayer_id,) if self.offensive else ()


@dataclass(frozen=True)
class ProtectionPrayer:
    prayer_id: str
    level: int
    damage_multiplier: Fraction


def _boost_table(mechanics: MechanicRegistry, mechanic_id: str) -> tuple[PrayerBoost, ...]:
    raw = mechanics.require(mechanic_id).value
    if not isinstance(raw, Mapping):
        raise DataUnavailableError(f"{mechanic_id} must be a mapping")
    boosts: list[PrayerBoost] = []
    for prayer_id, entry in raw.items():
        if not isinstance(prayer_id, str) or not isinstance(entry, Mapping):
            raise DataUnavailableError(f"{mechanic_id} has an invalid prayer entry")
        boosts.append(
            PrayerBoost(
                prayer_id=prayer_id,
                level=_int(entry.get("level"), f"{mechanic_id}.{prayer_id}.level"),
                multiplier=_fraction(entry.get("multiplier"), f"{mechanic_id}.{prayer_id}.multiplier"),
            )
        )
    return tuple(sorted(boosts, key=lambda boost: (boost.level, boost.prayer_id)))


def _combined_boost_table(
    mechanics: MechanicRegistry,
    *mechanic_ids: str,
) -> tuple[PrayerBoost, ...]:
    boosts: list[PrayerBoost] = []
    for mechanic_id in mechanic_ids:
        boosts.extend(_boost_table(mechanics, mechanic_id))
    return tuple(sorted(boosts, key=lambda boost: (boost.level, boost.prayer_id)))


def relevant_prayer_levels(
    mechanics: MechanicRegistry,
    *,
    include_protection: bool = False,
    include_magic: bool = True,
) -> tuple[int, ...]:
    levels = {1}
    for mechanic_id in (
        "prayer.f2p.attack_boosts",
        "prayer.f2p.strength_boosts",
        "prayer.f2p.ranged_boosts",
        "prayer.f2p.extra_ranged_boosts",
    ):
        levels.update(boost.level for boost in _boost_table(mechanics, mechanic_id))
    if include_magic:
        levels.update(boost.level for boost in _boost_table(mechanics, "prayer.f2p.magic_boosts"))
    if include_protection:
        protections = mechanics.require("prayer.pvp_protection").value
        if not isinstance(protections, Mapping):
            raise DataUnavailableError("prayer.pvp_protection must be a mapping")
        for style, entry in protections.items():
            if not isinstance(style, str) or not isinstance(entry, Mapping):
                raise DataUnavailableError("prayer.pvp_protection has an invalid style entry")
            levels.add(_int(entry.get("level"), f"prayer.pvp_protection.{style}.level"))
    return tuple(sorted(levels))


def best_melee_prayer_set(mechanics: MechanicRegistry, prayer_level: int) -> MeleePrayerSet:
    attack = [boost for boost in _boost_table(mechanics, "prayer.f2p.attack_boosts") if boost.level <= prayer_level]
    strength = [boost for boost in _boost_table(mechanics, "prayer.f2p.strength_boosts") if boost.level <= prayer_level]
    return MeleePrayerSet(
        attack=attack[-1] if attack else None,
        strength=strength[-1] if strength else None,
    )


def best_ranged_prayer_set(mechanics: MechanicRegistry, prayer_level: int) -> RangedPrayerSet:
    boosts = [
        boost
        for boost in _combined_boost_table(
            mechanics,
            "prayer.f2p.ranged_boosts",
            "prayer.f2p.extra_ranged_boosts",
        )
        if boost.level <= prayer_level
    ]
    return RangedPrayerSet(boosts[-1] if boosts else None)


def protection_prayer(
    mechanics: MechanicRegistry,
    style: str,
    prayer_level: int,
) -> ProtectionPrayer | None:
    protections = mechanics.require("prayer.pvp_protection").value
    if not isinstance(protections, Mapping):
        raise DataUnavailableError("prayer.pvp_protection must be a mapping")
    entry = protections.get(style)
    if entry is None:
        return None
    if not isinstance(entry, Mapping):
        raise DataUnavailableError(f"prayer.pvp_protection.{style} must be a mapping")
    level = _int(entry.get("level"), f"prayer.pvp_protection.{style}.level")
    if prayer_level < level:
        return None
    prayer_id = entry.get("prayer_id")
    if not isinstance(prayer_id, str) or not prayer_id:
        raise DataUnavailableError(f"prayer.pvp_protection.{style}.prayer_id is invalid")
    return ProtectionPrayer(
        prayer_id=prayer_id,
        level=level,
        damage_multiplier=_fraction(
            entry.get("damage_multiplier"),
            f"prayer.pvp_protection.{style}.damage_multiplier",
        ),
    )
