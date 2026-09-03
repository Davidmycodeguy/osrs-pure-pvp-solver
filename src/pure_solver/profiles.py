"""Verified melee and ranged attack profiles: effective levels, attack and defence rolls, hit chance and max hit
evaluated from pinned formulas, plus cooldown-aware offensive profiles for expected damage per tick.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from math import floor
from numbers import Number

from .errors import DataUnavailableError, VerifiedMechanicMissingError
from .evaluation import DamageDistribution
from .mechanics import Mechanic, MechanicRegistry


def _integer(value: int | Fraction, label: str) -> int:
    if isinstance(value, Fraction) and value.denominator != 1:
        raise DataUnavailableError(f"{label} did not resolve to an exact integer")
    return int(value)


@dataclass(frozen=True)
class VerifiedAttackTiming:
    cooldown_ticks: int
    impact_delay_by_distance: Mapping[int, int]
    minimum_distance: int
    maximum_distance: int
    source_ids: tuple[str, ...]
    status: str = "unverified"

    def validate(self) -> None:
        if self.status != "verified" or not self.source_ids:
            raise VerifiedMechanicMissingError("Attack timing has not been verified")
        if self.cooldown_ticks < 1:
            raise DataUnavailableError("Verified attack timing must have a positive cooldown")
        if self.minimum_distance < 0 or self.maximum_distance < self.minimum_distance:
            raise DataUnavailableError("Verified attack timing has an invalid distance range")
        if any(
            distance < self.minimum_distance or distance > self.maximum_distance or delay < 0
            for distance, delay in self.impact_delay_by_distance.items()
        ):
            raise DataUnavailableError("Verified impact-delay table contains an invalid distance or delay")

    def impact_delay(self, distance: int) -> int:
        self.validate()
        if not self.minimum_distance <= distance <= self.maximum_distance:
            raise DataUnavailableError(f"Attack is illegal at distance {distance}")
        if distance not in self.impact_delay_by_distance:
            raise VerifiedMechanicMissingError(f"No verified impact delay at distance {distance}")
        delay = self.impact_delay_by_distance[distance]
        if delay < 0:
            raise DataUnavailableError("Impact delay cannot be negative")
        return delay


@dataclass(frozen=True)
class TargetDefence:
    defence_level: int
    defence_bonus: int
    defence_boost: int = 0
    prayer_multiplier: Fraction = Fraction(1)
    style_bonus: int = 0


@dataclass(frozen=True)
class MeleeProfileInput:
    weapon_id: int
    attack_type: str
    attack_level: int
    strength_level: int
    attack_bonus: int
    strength_bonus: int
    timing: VerifiedAttackTiming
    attack_boost: int = 0
    strength_boost: int = 0
    attack_prayer_multiplier: Fraction = Fraction(1)
    strength_prayer_multiplier: Fraction = Fraction(1)
    attack_style_bonus: int = 0
    strength_style_bonus: int = 0


@dataclass(frozen=True)
class RangedProfileInput:
    weapon_id: int
    ranged_level: int
    ranged_attack_bonus: int
    ranged_strength_bonus: int
    timing: VerifiedAttackTiming
    ranged_boost: int = 0
    accuracy_prayer_multiplier: Fraction = Fraction(1)
    strength_prayer_multiplier: Fraction = Fraction(1)
    style_bonus: int = 0
    accuracy_void_multiplier: Fraction = Fraction(1)
    strength_void_multiplier: Fraction = Fraction(1)
    gear_multiplier: Fraction = Fraction(1)


@dataclass(frozen=True)
class DynamicMeleeDamage:
    melee_strength_bonus: int
    prayer_multiplier: Fraction
    style_bonus: int


@dataclass(frozen=True)
class AttackProfile:
    weapon_id: int
    damage_type: str
    attack_roll: int
    defence_roll: int
    hit_chance: Fraction
    max_hit: int
    timing: VerifiedAttackTiming
    successful_zero_becomes_one: bool
    formula_versions: tuple[str, ...]
    dynamic_melee: DynamicMeleeDamage | None = None
    self_defence_style_bonus: int = 0

    def distribution(self) -> DamageDistribution:
        return DamageDistribution.from_success_chance(self.hit_chance, self.max_hit, self.successful_zero_becomes_one)


@dataclass(frozen=True)
class OffensiveProfile:
    weapon_id: int
    damage_type: str
    attack_roll: int
    defence_roll: int
    hit_chance: Fraction
    max_hit: int
    cooldown_ticks: int
    successful_zero_becomes_one: bool
    formula_versions: tuple[str, ...]

    def distribution(self) -> DamageDistribution:
        return DamageDistribution.from_success_chance(self.hit_chance, self.max_hit, self.successful_zero_becomes_one)

    @property
    def expected_damage_per_attack(self) -> Fraction:
        return self.distribution().expected_damage

    @property
    def expected_damage_per_tick(self) -> Fraction:
        return self.expected_damage_per_attack / self.cooldown_ticks


def _player_defence_roll(mechanics: MechanicRegistry, target: TargetDefence) -> int:
    effective = mechanics.evaluate(
        "player.effective_defence",
        {
            "defence_level": target.defence_level,
            "defence_boost": target.defence_boost,
            "prayer_multiplier": target.prayer_multiplier,
            "style_bonus": target.style_bonus,
        },
    )
    return _integer(
        mechanics.evaluate(
            "player.defence_roll",
            {
                "effective_defence": effective,
                "defence_bonus": target.defence_bonus,
            },
        ),
        "player defence roll",
    )


def _melee_rolls(
    mechanics: MechanicRegistry,
    attacker: MeleeProfileInput,
    target: TargetDefence,
) -> tuple[int, int, Number, int, Mechanic, tuple[str, ...]]:
    effective_attack = mechanics.evaluate(
        "melee.effective_attack",
        {
            "attack_level": attacker.attack_level,
            "attack_boost": attacker.attack_boost,
            "prayer_multiplier": attacker.attack_prayer_multiplier,
            "style_bonus": attacker.attack_style_bonus,
        },
    )
    attack_roll = _integer(
        mechanics.evaluate(
            "melee.attack_roll",
            {
                "effective_attack": effective_attack,
                "attack_bonus": attacker.attack_bonus,
            },
        ),
        "melee attack roll",
    )
    effective_strength = mechanics.evaluate(
        "melee.effective_strength",
        {
            "strength_level": attacker.strength_level,
            "strength_boost": attacker.strength_boost,
            "prayer_multiplier": attacker.strength_prayer_multiplier,
            "style_bonus": attacker.strength_style_bonus,
        },
    )
    max_hit = _integer(
        mechanics.evaluate(
            "melee.max_hit",
            {
                "effective_strength": effective_strength,
                "melee_strength_bonus": attacker.strength_bonus,
            },
        ),
        "melee max hit",
    )
    defence_roll = _player_defence_roll(mechanics, target)
    accuracy = mechanics.evaluate(
        "melee.accuracy",
        {
            "attack_roll": attack_roll,
            "defence_roll": defence_roll,
        },
    )
    zero_rule = mechanics.require("damage.player_successful_zero_to_one")
    versions = tuple(
        mechanics.require(mechanic_id).formula_version
        for mechanic_id in (
            "melee.effective_attack",
            "melee.attack_roll",
            "melee.effective_strength",
            "melee.max_hit",
            "player.effective_defence",
            "player.defence_roll",
            "melee.accuracy",
            "damage.player_successful_zero_to_one",
        )
    )
    return attack_roll, defence_roll, accuracy, max_hit, zero_rule, versions


def _ranged_rolls(
    mechanics: MechanicRegistry,
    attacker: RangedProfileInput,
    target: TargetDefence,
) -> tuple[int, int, Number, int, Mechanic, tuple[str, ...]]:
    effective_attack = mechanics.evaluate(
        "ranged.effective_attack",
        {
            "ranged_level": attacker.ranged_level,
            "ranged_boost": attacker.ranged_boost,
            "prayer_multiplier": attacker.accuracy_prayer_multiplier,
            "style_bonus": attacker.style_bonus,
            "void_multiplier": attacker.accuracy_void_multiplier,
        },
    )
    effective_strength = mechanics.evaluate(
        "ranged.effective_strength",
        {
            "ranged_level": attacker.ranged_level,
            "ranged_boost": attacker.ranged_boost,
            "prayer_multiplier": attacker.strength_prayer_multiplier,
            "style_bonus": attacker.style_bonus,
            "void_multiplier": attacker.strength_void_multiplier,
        },
    )
    attack_roll = _integer(
        mechanics.evaluate(
            "ranged.attack_roll",
            {
                "effective_ranged_attack": effective_attack,
                "ranged_attack_bonus": attacker.ranged_attack_bonus,
                "gear_multiplier": attacker.gear_multiplier,
            },
        ),
        "ranged attack roll",
    )
    max_hit = _integer(
        mechanics.evaluate(
            "ranged.max_hit",
            {
                "effective_ranged_strength": effective_strength,
                "ranged_strength_bonus": attacker.ranged_strength_bonus,
                "gear_multiplier": attacker.gear_multiplier,
            },
        ),
        "ranged max hit",
    )
    defence_roll = _player_defence_roll(mechanics, target)
    accuracy = mechanics.evaluate(
        "melee.accuracy",
        {
            "attack_roll": attack_roll,
            "defence_roll": defence_roll,
        },
    )
    zero_rule = mechanics.require("damage.player_successful_zero_to_one")
    versions = tuple(
        mechanics.require(mechanic_id).formula_version
        for mechanic_id in (
            "ranged.effective_attack",
            "ranged.effective_strength",
            "ranged.attack_roll",
            "ranged.max_hit",
            "player.effective_defence",
            "player.defence_roll",
            "melee.accuracy",
            "damage.player_successful_zero_to_one",
        )
    )
    return attack_roll, defence_roll, accuracy, max_hit, zero_rule, versions


def build_melee_profile(
    mechanics: MechanicRegistry,
    attacker: MeleeProfileInput,
    target: TargetDefence,
) -> AttackProfile:
    attacker.timing.validate()
    attack_roll, defence_roll, accuracy, max_hit, zero_rule, versions = _melee_rolls(mechanics, attacker, target)
    return AttackProfile(
        attacker.weapon_id,
        attacker.attack_type,
        attack_roll,
        defence_roll,
        Fraction(accuracy),
        max_hit,
        attacker.timing,
        bool(zero_rule.value),
        versions,
        DynamicMeleeDamage(
            attacker.strength_bonus,
            attacker.strength_prayer_multiplier,
            attacker.strength_style_bonus,
        ),
    )


def build_ranged_profile(
    mechanics: MechanicRegistry,
    attacker: RangedProfileInput,
    target: TargetDefence,
) -> AttackProfile:
    attacker.timing.validate()
    attack_roll, defence_roll, accuracy, max_hit, zero_rule, versions = _ranged_rolls(mechanics, attacker, target)
    return AttackProfile(
        attacker.weapon_id,
        "ranged",
        attack_roll,
        defence_roll,
        Fraction(accuracy),
        max_hit,
        attacker.timing,
        bool(zero_rule.value),
        versions,
    )


def _scaled_hit(max_hit: int, multiplier: Fraction) -> int:
    if multiplier <= 0:
        raise DataUnavailableError("Damage multiplier must be positive")
    return floor(Fraction(max_hit) * multiplier)


def build_melee_offensive_profile(
    mechanics: MechanicRegistry,
    attacker: MeleeProfileInput,
    target: TargetDefence,
    *,
    cooldown_ticks: int,
    damage_multiplier: Fraction = Fraction(1),
) -> OffensiveProfile:
    if cooldown_ticks < 1:
        raise DataUnavailableError("Melee cooldown must be positive")
    attack_roll, defence_roll, accuracy, max_hit, zero_rule, versions = _melee_rolls(mechanics, attacker, target)
    return OffensiveProfile(
        weapon_id=attacker.weapon_id,
        damage_type=attacker.attack_type,
        attack_roll=attack_roll,
        defence_roll=defence_roll,
        hit_chance=Fraction(accuracy),
        max_hit=_scaled_hit(max_hit, damage_multiplier),
        cooldown_ticks=cooldown_ticks,
        successful_zero_becomes_one=bool(zero_rule.value),
        formula_versions=versions,
    )


def build_ranged_offensive_profile(
    mechanics: MechanicRegistry,
    attacker: RangedProfileInput,
    target: TargetDefence,
    *,
    cooldown_ticks: int,
    damage_multiplier: Fraction = Fraction(1),
) -> OffensiveProfile:
    if cooldown_ticks < 1:
        raise DataUnavailableError("Ranged cooldown must be positive")
    attack_roll, defence_roll, accuracy, max_hit, zero_rule, versions = _ranged_rolls(mechanics, attacker, target)
    return OffensiveProfile(
        weapon_id=attacker.weapon_id,
        damage_type="ranged",
        attack_roll=attack_roll,
        defence_roll=defence_roll,
        hit_chance=Fraction(accuracy),
        max_hit=_scaled_hit(max_hit, damage_multiplier),
        cooldown_ticks=cooldown_ticks,
        successful_zero_becomes_one=bool(zero_rule.value),
        formula_versions=versions,
    )
