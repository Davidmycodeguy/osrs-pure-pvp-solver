"""Account skill profiles and search bounds for 1-Defence F2P pures.

``AccountState`` carries the seven combat levels (plus optional XP) and computes the pinned combat level
through the mechanic registry; ``LevelRange`` and ``AccountSearchBounds`` describe a search box that
``enumerate_account_states`` walks lazily under an explicit candidate budget. ``AccountState`` is ported to
Rust in ``pure_math/src/accounts.rs``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction

from .canonical import canonical_hash
from .errors import SearchBudgetExceeded
from .mechanics import MechanicRegistry


@dataclass(frozen=True)
class AccountState:
    attack_level: int
    strength_level: int
    ranged_level: int
    magic_level: int
    prayer_level: int
    hitpoints_level: int
    defence_level: int = 1
    attack_xp: int | None = None
    strength_xp: int | None = None
    ranged_xp: int | None = None
    magic_xp: int | None = None
    prayer_xp: int | None = None
    hitpoints_xp: int | None = None
    defence_xp: int | None = None

    def __post_init__(self) -> None:
        values = {
            "attack": self.attack_level,
            "strength": self.strength_level,
            "ranged": self.ranged_level,
            "magic": self.magic_level,
            "prayer": self.prayer_level,
            "hitpoints": self.hitpoints_level,
            "defence": self.defence_level,
        }
        invalid = [name for name, level in values.items() if not 1 <= level <= 99]
        if invalid:
            raise ValueError(f"Skill levels must be between 1 and 99: {', '.join(invalid)}")
        if self.defence_level != 1:
            raise ValueError("The F2P pure search is defined only for 1 Defence accounts")

    @property
    def canonical_id(self) -> str:
        return canonical_hash(self)

    def combat_level(self, mechanics: MechanicRegistry) -> int:
        mechanic = mechanics.require("combat_level")
        if mechanic.formula_version == "osrs-wiki-combat-level-15305725":
            # Exact compiled form of the pinned JSON formula. All terms share a
            # denominator of 160, preserving the outer floor without Fraction
            # allocation or repeated AST traversal.
            base_numerator = 40 * (self.defence_level + self.hitpoints_level + self.prayer_level // 2)
            dominant = max(
                self.attack_level + self.strength_level,
                (self.ranged_level * 3) // 2,
                (self.magic_level * 3) // 2,
            )
            return (base_numerator + 52 * dominant) // 160
        value = mechanics.evaluate(
            "combat_level",
            {
                "attack": self.attack_level,
                "strength": self.strength_level,
                "ranged": self.ranged_level,
                "magic": self.magic_level,
                "prayer": self.prayer_level,
                "hitpoints": self.hitpoints_level,
                "defence": self.defence_level,
            },
        )
        if not isinstance(value, (int, Fraction)) or value.denominator != 1:
            raise ValueError("Verified combat-level formula must resolve to an integer")
        return int(value)


@dataclass(frozen=True)
class LevelRange:
    minimum: int
    maximum: int

    def values(self) -> range:
        if self.minimum < 1 or self.maximum > 99 or self.minimum > self.maximum:
            raise ValueError(f"Invalid legal level range {self.minimum}..{self.maximum}")
        return range(self.minimum, self.maximum + 1)


@dataclass(frozen=True)
class AccountSearchBounds:
    attack: LevelRange
    strength: LevelRange
    ranged: LevelRange
    magic: LevelRange
    prayer: LevelRange
    hitpoints: LevelRange
    combat_minimum: int = 30
    combat_maximum: int = 40


def enumerate_account_states(
    bounds: AccountSearchBounds,
    mechanics: MechanicRegistry,
    *,
    max_candidates: int | None = None,
) -> Iterator[AccountState]:
    """Yield every in-range 1-Defence candidate lazily.

    `max_candidates` is an explicit safety stop, never an implicit sampled
    result. Callers must surface SearchBudgetExceeded rather than labelling a
    truncated search exhaustive.
    """
    yielded = 0
    attack_values = bounds.attack.values()
    strength_values = bounds.strength.values()
    ranged_values = bounds.ranged.values()
    magic_values = bounds.magic.values()

    def state_for(attack: int, strength: int, ranged: int, magic: int, prayer: int, hitpoints: int) -> AccountState:
        return AccountState(attack, strength, ranged, magic, prayer, hitpoints)

    def first_magic_at_least(
        attack: int, strength: int, ranged: int, prayer: int, hitpoints: int, target: int
    ) -> int | None:
        low, high = magic_values.start, magic_values.stop - 1
        if state_for(attack, strength, ranged, high, prayer, hitpoints).combat_level(mechanics) < target:
            return None
        while low < high:
            middle = (low + high) // 2
            if state_for(attack, strength, ranged, middle, prayer, hitpoints).combat_level(mechanics) >= target:
                high = middle
            else:
                low = middle + 1
        return low

    def last_magic_at_most(
        attack: int, strength: int, ranged: int, prayer: int, hitpoints: int, target: int
    ) -> int | None:
        low, high = magic_values.start, magic_values.stop - 1
        if state_for(attack, strength, ranged, low, prayer, hitpoints).combat_level(mechanics) > target:
            return None
        while low < high:
            middle = (low + high + 1) // 2
            if state_for(attack, strength, ranged, middle, prayer, hitpoints).combat_level(mechanics) <= target:
                low = middle
            else:
                high = middle - 1
        return low

    # Combat level is monotone in every input of the pinned formula. Use the
    # lowest remaining levels to reject impossible prefixes, then binary-search
    # the final Magic interval. Every retained state is still evaluated by the
    # authoritative formula before being yielded.
    for hitpoints in bounds.hitpoints.values():
        for prayer in bounds.prayer.values():
            global_min = state_for(
                attack_values.start,
                strength_values.start,
                ranged_values.start,
                magic_values.start,
                prayer,
                hitpoints,
            ).combat_level(mechanics)
            global_max = state_for(
                attack_values.stop - 1,
                strength_values.stop - 1,
                ranged_values.stop - 1,
                magic_values.stop - 1,
                prayer,
                hitpoints,
            ).combat_level(mechanics)
            if global_min > bounds.combat_maximum or global_max < bounds.combat_minimum:
                continue
            for attack in attack_values:
                for strength in strength_values:
                    prefix_min = state_for(
                        attack,
                        strength,
                        ranged_values.start,
                        magic_values.start,
                        prayer,
                        hitpoints,
                    ).combat_level(mechanics)
                    if prefix_min > bounds.combat_maximum:
                        continue
                    for ranged in ranged_values:
                        ranged_min = state_for(
                            attack,
                            strength,
                            ranged,
                            magic_values.start,
                            prayer,
                            hitpoints,
                        ).combat_level(mechanics)
                        if ranged_min > bounds.combat_maximum:
                            break
                        magic_min = first_magic_at_least(
                            attack, strength, ranged, prayer, hitpoints, bounds.combat_minimum
                        )
                        magic_max = last_magic_at_most(
                            attack, strength, ranged, prayer, hitpoints, bounds.combat_maximum
                        )
                        if magic_min is None or magic_max is None or magic_min > magic_max:
                            continue
                        for magic in range(magic_min, magic_max + 1):
                            state = state_for(attack, strength, ranged, magic, prayer, hitpoints)
                            combat_level = state.combat_level(mechanics)
                            if not bounds.combat_minimum <= combat_level <= bounds.combat_maximum:
                                continue
                            if max_candidates is not None and yielded >= max_candidates:
                                raise SearchBudgetExceeded(
                                    f"Account search reached its explicit {max_candidates}-candidate budget; "
                                    "result is not exhaustive."
                                )
                            yielded += 1
                            yield state
