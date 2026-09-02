"""F2P spell definitions loaded from verified mechanics, and exact magic attack profiles (attack roll, defence
roll, hit chance, max hit, damage PMF).

Verified mechanic primitive that is not yet wired into the ranking pipeline; it is exercised by the test
suite.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from .errors import DataUnavailableError, VerifiedMechanicMissingError
from .evaluation import DamageDistribution
from .mechanics import ImpactTiming, MechanicRegistry


@dataclass(frozen=True)
class SpellDefinition:
    spell_id: str
    name: str
    magic_level: int
    base_max_hit: int
    rune_cost: Mapping[str, int]
    attack_speed_ticks: int
    bind_duration_ticks: int = 0
    free_to_play: bool = True
    source_ids: tuple[str, ...] = ()
    status: str = "unverified"

    def validate(self, available_source_ids: set[str]) -> None:
        if self.status != "verified" or not self.source_ids:
            raise VerifiedMechanicMissingError(f"Spell {self.spell_id!r} is not verified")
        if set(self.source_ids) - available_source_ids:
            raise DataUnavailableError(f"Spell {self.spell_id!r} cites unavailable sources")
        if not self.free_to_play or self.magic_level < 1 or self.base_max_hit < 0:
            raise DataUnavailableError(f"Spell {self.spell_id!r} is not legal F2P combat data")
        if self.attack_speed_ticks < 1 or any(quantity < 1 for quantity in self.rune_cost.values()):
            raise DataUnavailableError(f"Spell {self.spell_id!r} has invalid speed or rune cost")

    def can_cast(self, magic_level: int, runes: Mapping[str, int]) -> bool:
        return magic_level >= self.magic_level and all(
            runes.get(rune, 0) >= quantity for rune, quantity in self.rune_cost.items()
        )


class MagicBook:
    def __init__(self, spells: Mapping[str, SpellDefinition]):
        self.spells = dict(spells)

    @classmethod
    def from_mechanics(cls, mechanics: MechanicRegistry) -> MagicBook:
        mechanic = mechanics.require("magic.f2p.spells")
        if not isinstance(mechanic.value, Mapping):
            raise DataUnavailableError("magic.f2p.spells must be a mapping")
        spells: dict[str, SpellDefinition] = {}
        sources = set(mechanics.source_revisions)
        for spell_id, raw in mechanic.value.items():
            if not isinstance(raw, Mapping):
                raise DataUnavailableError(f"Spell {spell_id!r} is not a mapping")
            spell = SpellDefinition(
                spell_id=str(spell_id),
                name=str(raw["name"]),
                magic_level=int(raw["magic_level"]),
                base_max_hit=int(raw["base_max_hit"]),
                rune_cost={str(rune): int(quantity) for rune, quantity in raw["rune_cost"].items()},
                attack_speed_ticks=int(raw["attack_speed_ticks"]),
                bind_duration_ticks=int(raw.get("bind_duration_ticks", 0)),
                free_to_play=bool(raw["free_to_play"]),
                source_ids=tuple(map(str, raw["source_ids"])),
                status=str(raw["status"]),
            )
            spell.validate(sources)
            spells[spell.spell_id] = spell
        return cls(spells)

    def available(self, magic_level: int) -> tuple[SpellDefinition, ...]:
        return tuple(
            sorted(
                (spell for spell in self.spells.values() if spell.magic_level <= magic_level),
                key=lambda spell: (spell.magic_level, spell.spell_id),
            )
        )


@dataclass(frozen=True)
class MagicAttackProfile:
    spell: SpellDefinition
    attack_roll: int
    defence_roll: int
    hit_chance: Fraction
    max_hit: int
    distribution: DamageDistribution
    timing: ImpactTiming


def build_magic_attack_profile(
    mechanics: MechanicRegistry,
    spell: SpellDefinition,
    *,
    magic_level: int,
    magic_boost: int,
    prayer_multiplier: Fraction,
    magic_attack_bonus: int,
    target_defence_roll: int,
    magic_damage_percent: int = 0,
) -> MagicAttackProfile:
    spell.validate(set(mechanics.source_revisions))
    if magic_level + magic_boost < spell.magic_level:
        raise DataUnavailableError(f"Magic level is too low for {spell.name}")
    effective = mechanics.evaluate(
        "magic.effective_attack",
        {
            "magic_level": magic_level,
            "magic_boost": magic_boost,
            "prayer_multiplier": prayer_multiplier,
            "style_bonus": 0,
        },
    )
    attack_roll = int(
        mechanics.evaluate(
            "magic.attack_roll",
            {
                "effective_magic_attack": effective,
                "magic_attack_bonus": magic_attack_bonus,
            },
        )
    )
    hit_chance = Fraction(
        mechanics.evaluate(
            "melee.accuracy",
            {
                "attack_roll": attack_roll,
                "defence_roll": target_defence_roll,
            },
        )
    )
    max_hit = int(
        mechanics.evaluate(
            "magic.max_hit",
            {
                "spell_base_max_hit": spell.base_max_hit,
                "magic_damage_percent": magic_damage_percent,
            },
        )
    )
    zero_rule = bool(mechanics.require("damage.player_successful_zero_to_one").value)
    timing = ImpactTiming.from_mechanic(mechanics.require("magic.projectile_timing"))
    return MagicAttackProfile(
        spell,
        attack_roll,
        target_defence_roll,
        hit_chance,
        max_hit,
        DamageDistribution.from_success_chance(hit_chance, max_hit, zero_rule),
        timing,
    )
