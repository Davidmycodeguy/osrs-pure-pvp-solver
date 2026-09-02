"""Full F2P prayer catalogue for tick-level simulation: ``PrayerDefinition`` records, ``PrayerState`` with points
and drain, activation with group conflicts, per-tick drain with the single-tick flick rule, and the resulting
``PrayerModifiers``.

Distinct from :mod:`pure_solver.prayers`, which only picks the best verified boost set for a prayer level and
is what the closed-form ranking pipeline uses.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from .errors import DataUnavailableError, VerifiedMechanicMissingError
from .mechanics import MechanicRegistry


def _fraction(value: object, label: str) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value, 1)
    if isinstance(value, Mapping) and set(value) == {"numerator", "denominator"}:
        return Fraction(int(value["numerator"]), int(value["denominator"]))
    raise DataUnavailableError(f"{label} must be an integer or fraction mapping")


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DataUnavailableError(f"{label} must be an integer")
    return value


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise DataUnavailableError(f"{label} must be a non-empty string list")
    return tuple(value)


@dataclass(frozen=True)
class PrayerDefinition:
    prayer_id: str
    display_name: str
    level: int
    drain_effect: int
    group: str
    conflicts_with_groups: tuple[str, ...]
    source_ids: tuple[str, ...]
    melee_attack_multiplier: Fraction = Fraction(1)
    melee_strength_multiplier: Fraction = Fraction(1)
    ranged_attack_multiplier: Fraction = Fraction(1)
    ranged_strength_multiplier: Fraction = Fraction(1)
    magic_attack_multiplier: Fraction = Fraction(1)
    magic_defence_multiplier: Fraction = Fraction(1)
    magic_damage_multiplier: Fraction = Fraction(1)
    overhead: bool = False
    protection_style: str | None = None

    def validate(self) -> None:
        if not self.prayer_id or not self.display_name:
            raise DataUnavailableError("Prayer definitions require stable ids and display names")
        if self.level < 1:
            raise DataUnavailableError(f"{self.prayer_id!r} has an invalid level requirement")
        if self.drain_effect < 0:
            raise DataUnavailableError(f"{self.prayer_id!r} has a negative drain effect")
        if not self.group:
            raise DataUnavailableError(f"{self.prayer_id!r} has no conflict group")
        if any(not group for group in self.conflicts_with_groups):
            raise DataUnavailableError(f"{self.prayer_id!r} has an invalid conflict group entry")
        if self.overhead != (self.protection_style is not None):
            raise DataUnavailableError(f"{self.prayer_id!r} must mark overhead prayers with a protection style")
        if not self.source_ids:
            raise DataUnavailableError(f"{self.prayer_id!r} has no source provenance")


@dataclass(frozen=True)
class PrayerState:
    prayer_level: int
    current_points: int
    drain_counter: int = 0
    active_prayer_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.prayer_level < 1:
            raise DataUnavailableError("Prayer level must be at least 1")
        if self.current_points < 0:
            raise DataUnavailableError("Prayer points cannot be negative")
        if self.current_points > self.prayer_level:
            raise DataUnavailableError("Prayer points cannot exceed the account's prayer level")
        if self.drain_counter < 0:
            raise DataUnavailableError("Prayer drain counter cannot be negative")


@dataclass(frozen=True)
class PrayerModifiers:
    melee_attack: Fraction = Fraction(1)
    melee_strength: Fraction = Fraction(1)
    ranged_attack: Fraction = Fraction(1)
    ranged_strength: Fraction = Fraction(1)
    magic_attack: Fraction = Fraction(1)
    magic_defence: Fraction = Fraction(1)
    magic_damage: Fraction = Fraction(1)


class PrayerBook:
    def __init__(
        self,
        prayers: tuple[PrayerDefinition, ...],
        base_resistance: int,
        resistance_per_bonus: int,
        pvp_protection_multiplier: Fraction,
        protection_affects_accuracy: bool,
        single_tick_flick_no_drain: bool,
    ) -> None:
        if base_resistance <= 0 or resistance_per_bonus < 0:
            raise DataUnavailableError("Prayer drain resistance constants are invalid")
        by_id: dict[str, PrayerDefinition] = {}
        for prayer in prayers:
            prayer.validate()
            if prayer.prayer_id in by_id:
                raise DataUnavailableError(f"Duplicate prayer definition {prayer.prayer_id!r}")
            by_id[prayer.prayer_id] = prayer
        self._prayers = by_id
        self.base_resistance = base_resistance
        self.resistance_per_bonus = resistance_per_bonus
        self.pvp_protection_multiplier = pvp_protection_multiplier
        self.protection_affects_accuracy = protection_affects_accuracy
        self.single_tick_flick_no_drain = single_tick_flick_no_drain

    @classmethod
    def from_mechanics(cls, mechanics: MechanicRegistry) -> PrayerBook:
        attack_boosts = mechanics.require("prayer.f2p.attack_boosts")
        strength_boosts = mechanics.require("prayer.f2p.strength_boosts")
        ranged_boosts = mechanics.require("prayer.f2p.ranged_boosts")
        extra_ranged_boosts = mechanics.require("prayer.f2p.extra_ranged_boosts")
        magic_boosts = mechanics.require("prayer.f2p.magic_boosts")
        drain_effects = mechanics.require("prayer.f2p.drain_effects")
        conflicts = mechanics.require("prayer.f2p.conflicts")
        drain_base = mechanics.require("prayer.drain.base_resistance")
        drain_bonus = mechanics.require("prayer.drain.per_bonus_resistance")
        protection = mechanics.require("prayer.pvp_protection")
        protection_accuracy = mechanics.require("prayer.pvp_protection_affects_accuracy")
        flick = mechanics.require("prayer.flick.single_tick_no_drain")
        prayers: list[PrayerDefinition] = []
        prayers.extend(
            cls._load_boost_group(
                attack_boosts.value,
                conflicts.value,
                drain_effects.value,
                source_ids=attack_boosts.source_ids,
                group="attack",
                multiplier_field="melee_attack_multiplier",
            )
        )
        prayers.extend(
            cls._load_boost_group(
                strength_boosts.value,
                conflicts.value,
                drain_effects.value,
                source_ids=strength_boosts.source_ids,
                group="strength",
                multiplier_field="melee_strength_multiplier",
            )
        )
        prayers.extend(
            cls._load_boost_group(
                ranged_boosts.value,
                conflicts.value,
                drain_effects.value,
                source_ids=ranged_boosts.source_ids,
                group="ranged",
                multiplier_field="ranged_attack_multiplier",
                paired_multiplier_field="ranged_strength_multiplier",
            )
        )
        prayers.extend(
            cls._load_boost_group(
                extra_ranged_boosts.value,
                conflicts.value,
                drain_effects.value,
                source_ids=extra_ranged_boosts.source_ids,
                group="ranged",
                multiplier_field="ranged_attack_multiplier",
                paired_multiplier_field="ranged_strength_multiplier",
            )
        )
        prayers.extend(
            cls._load_boost_group(
                magic_boosts.value,
                conflicts.value,
                drain_effects.value,
                source_ids=magic_boosts.source_ids,
                group="magic",
                multiplier_field="magic_attack_multiplier",
                paired_multiplier_field="magic_defence_multiplier",
                extra_multiplier_field="magic_damage_multiplier",
            )
        )
        if not isinstance(protection.value, Mapping):
            raise DataUnavailableError("prayer.pvp_protection must be a mapping")
        if not isinstance(conflicts.value, Mapping):
            raise DataUnavailableError("prayer.f2p.conflicts must be a mapping")
        if not isinstance(drain_effects.value, Mapping):
            raise DataUnavailableError("prayer.f2p.drain_effects must be a mapping")
        for style, item in protection.value.items():
            if not isinstance(item, Mapping):
                raise DataUnavailableError("prayer.pvp_protection entries must be mappings")
            prayer_id = str(item["prayer_id"])
            group, conflict_groups = cls._conflict_payload(conflicts.value, prayer_id)
            prayers.append(
                PrayerDefinition(
                    prayer_id=prayer_id,
                    display_name=cls._display_name(prayer_id),
                    level=_integer(item["level"], f"{prayer_id}.level"),
                    drain_effect=_integer(drain_effects.value[prayer_id], f"{prayer_id}.drain_effect"),
                    group=group,
                    conflicts_with_groups=conflict_groups,
                    source_ids=tuple(protection.source_ids),
                    overhead=True,
                    protection_style=str(style),
                )
            )
        return cls(
            tuple(prayers),
            _integer(drain_base.value, "prayer.drain.base_resistance"),
            _integer(drain_bonus.value, "prayer.drain.per_bonus_resistance"),
            cls._shared_protection_multiplier(protection.value),
            bool(protection_accuracy.value),
            bool(flick.value),
        )

    @staticmethod
    def _load_boost_group(
        value: object,
        conflicts: object,
        drain_effects: object,
        *,
        source_ids: tuple[str, ...],
        group: str,
        multiplier_field: str,
        paired_multiplier_field: str | None = None,
        extra_multiplier_field: str | None = None,
    ) -> list[PrayerDefinition]:
        if not isinstance(value, Mapping):
            raise DataUnavailableError(f"Prayer boost mechanic for {group} must be a mapping")
        if not isinstance(conflicts, Mapping):
            raise DataUnavailableError("prayer.f2p.conflicts must be a mapping")
        if not isinstance(drain_effects, Mapping):
            raise DataUnavailableError("prayer.f2p.drain_effects must be a mapping")
        prayers: list[PrayerDefinition] = []
        for prayer_id, item in value.items():
            if not isinstance(item, Mapping):
                raise DataUnavailableError(f"{prayer_id}.boost entry must be a mapping")
            prayer_group, conflict_groups = PrayerBook._conflict_payload(conflicts, str(prayer_id))
            multipliers = {
                multiplier_field: _fraction(item["multiplier"], f"{prayer_id}.multiplier"),
            }
            if paired_multiplier_field is not None:
                multipliers[paired_multiplier_field] = _fraction(item["multiplier"], f"{prayer_id}.multiplier")
            if extra_multiplier_field is not None:
                multipliers[extra_multiplier_field] = _fraction(
                    item.get("magic_damage_multiplier", 1),
                    f"{prayer_id}.magic_damage_multiplier",
                )
            prayers.append(
                PrayerDefinition(
                    prayer_id=str(prayer_id),
                    display_name=PrayerBook._display_name(str(prayer_id)),
                    level=_integer(item["level"], f"{prayer_id}.level"),
                    drain_effect=_integer(drain_effects[str(prayer_id)], f"{prayer_id}.drain_effect"),
                    group=prayer_group or group,
                    conflicts_with_groups=conflict_groups,
                    source_ids=tuple(source_ids),
                    **multipliers,
                )
            )
        return prayers

    @staticmethod
    def _conflict_payload(conflicts: Mapping[str, object], prayer_id: str) -> tuple[str, tuple[str, ...]]:
        item = conflicts.get(prayer_id)
        if not isinstance(item, Mapping):
            raise DataUnavailableError(f"Missing conflict payload for {prayer_id}")
        group = str(item["group"])
        groups = _string_tuple(item["conflicts_with_groups"], f"{prayer_id}.conflicts_with_groups")
        return group, groups

    @staticmethod
    def _display_name(prayer_id: str) -> str:
        return prayer_id.replace("_", " ").title().replace(" Of ", " of ")

    @staticmethod
    def _shared_protection_multiplier(value: Mapping[str, object]) -> Fraction:
        multipliers: set[Fraction] = set()
        for style, item in value.items():
            if not isinstance(item, Mapping):
                raise DataUnavailableError(f"prayer.pvp_protection[{style!r}] must be a mapping")
            multipliers.add(_fraction(item["damage_multiplier"], f"{style}.damage_multiplier"))
        if not multipliers:
            raise DataUnavailableError("prayer.pvp_protection has no entries")
        if len(multipliers) != 1:
            raise DataUnavailableError("Protection prayers do not share one PvP damage multiplier")
        return next(iter(multipliers))

    def get(self, prayer_id: str) -> PrayerDefinition:
        prayer = self._prayers.get(prayer_id)
        if prayer is None:
            raise VerifiedMechanicMissingError(f"Unknown prayer {prayer_id!r}")
        return prayer

    def empty_state(self, prayer_level: int, current_points: int | None = None) -> PrayerState:
        points = prayer_level if current_points is None else current_points
        state = PrayerState(prayer_level=prayer_level, current_points=points)
        state.validate()
        return state

    def active_prayers(self, state: PrayerState) -> tuple[PrayerDefinition, ...]:
        self._validate_state(state)
        return tuple(self.get(prayer_id) for prayer_id in state.active_prayer_ids)

    def drain_resistance(self, prayer_bonus: int) -> int:
        if prayer_bonus < 0:
            raise DataUnavailableError("Prayer bonus cannot be negative")
        return self.base_resistance + (self.resistance_per_bonus * prayer_bonus)

    def activate(self, state: PrayerState, prayer_id: str) -> PrayerState:
        self._validate_state(state)
        prayer = self.get(prayer_id)
        if state.current_points <= 0:
            raise DataUnavailableError("Cannot activate a prayer with zero prayer points")
        if prayer.level > state.prayer_level:
            raise DataUnavailableError(f"Prayer level {state.prayer_level} cannot activate {prayer.display_name}")
        retained: list[str] = []
        for active_id in state.active_prayer_ids:
            active = self.get(active_id)
            if self._conflicts(prayer, active):
                continue
            retained.append(active_id)
        if prayer.prayer_id not in retained:
            retained.append(prayer.prayer_id)
        return PrayerState(
            prayer_level=state.prayer_level,
            current_points=state.current_points,
            drain_counter=state.drain_counter,
            active_prayer_ids=tuple(sorted(retained)),
        )

    def deactivate(self, state: PrayerState, prayer_id: str) -> PrayerState:
        self._validate_state(state)
        retained = tuple(active_id for active_id in state.active_prayer_ids if active_id != prayer_id)
        drain_counter = state.drain_counter
        if not retained and self.single_tick_flick_no_drain:
            drain_counter = 0
        return PrayerState(
            prayer_level=state.prayer_level,
            current_points=state.current_points,
            drain_counter=drain_counter,
            active_prayer_ids=retained,
        )

    def advance_tick(self, state: PrayerState, prayer_bonus: int = 0) -> PrayerState:
        self._validate_state(state)
        if not state.active_prayer_ids:
            return state
        resistance = self.drain_resistance(prayer_bonus)
        total_effect = sum(prayer.drain_effect for prayer in self.active_prayers(state))
        counter = state.drain_counter + total_effect
        points = state.current_points
        while counter >= resistance and points > 0:
            counter -= resistance
            points -= 1
        if points == 0:
            return PrayerState(state.prayer_level, 0, 0, ())
        return PrayerState(state.prayer_level, points, counter, state.active_prayer_ids)

    def modifiers(self, state: PrayerState) -> PrayerModifiers:
        self._validate_state(state)
        prayers = self.active_prayers(state)
        return PrayerModifiers(
            melee_attack=max((prayer.melee_attack_multiplier for prayer in prayers), default=Fraction(1)),
            melee_strength=max((prayer.melee_strength_multiplier for prayer in prayers), default=Fraction(1)),
            ranged_attack=max((prayer.ranged_attack_multiplier for prayer in prayers), default=Fraction(1)),
            ranged_strength=max((prayer.ranged_strength_multiplier for prayer in prayers), default=Fraction(1)),
            magic_attack=max((prayer.magic_attack_multiplier for prayer in prayers), default=Fraction(1)),
            magic_defence=max((prayer.magic_defence_multiplier for prayer in prayers), default=Fraction(1)),
            magic_damage=max((prayer.magic_damage_multiplier for prayer in prayers), default=Fraction(1)),
        )

    def damage_taken_multiplier(
        self,
        state: PrayerState,
        damage_style: str,
        *,
        attacker_is_player: bool,
    ) -> Fraction:
        self._validate_state(state)
        style = damage_style.lower()
        for prayer in self.active_prayers(state):
            if prayer.protection_style == style:
                return self.pvp_protection_multiplier if attacker_is_player else Fraction(0)
        return Fraction(1)

    def _validate_state(self, state: PrayerState) -> None:
        state.validate()
        for prayer_id in state.active_prayer_ids:
            prayer = self.get(prayer_id)
            if prayer.level > state.prayer_level:
                raise DataUnavailableError(
                    f"Prayer state illegally contains {prayer.display_name} above the account level"
                )

    @staticmethod
    def _conflicts(left: PrayerDefinition, right: PrayerDefinition) -> bool:
        return right.group in left.conflicts_with_groups or left.group in right.conflicts_with_groups
