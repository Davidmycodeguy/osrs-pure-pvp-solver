"""Deterministic logical-tick duel simulator: actors, scheduled hits, tick intents, restricted and scripted
policies, and ``DuelSimulator`` itself, with every timing rule taken from verified mechanics rather than hard-
coded constants.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from fractions import Fraction
from typing import Protocol

from .errors import DataUnavailableError, VerifiedMechanicMissingError
from .events import TerminalStatus, TickPipeline
from .inventory import InventoryEntry, InventoryState
from .mechanics import MechanicRegistry
from .profiles import AttackProfile


@dataclass(frozen=True)
class DuelRules:
    pipeline_id: str
    simultaneous_ko: TerminalStatus
    maximum_ticks: int
    switch_and_attack_same_tick: bool
    source_ids: tuple[str, ...]
    status: str = "unverified"
    attack_and_eat_same_tick: bool = False
    priority_order: tuple[str, ...] = ("player", "opponent")

    @classmethod
    def from_mechanics(
        cls,
        mechanics: MechanicRegistry,
        *,
        maximum_ticks: int,
        switch_and_attack_same_tick: bool,
        attack_and_eat_same_tick: bool = False,
    ) -> DuelRules:
        pipeline_mechanic = mechanics.require("tick.pipeline")
        pipeline = TickPipeline.from_mechanics(mechanics)
        outcome_mechanic = mechanics.require("death.simultaneous_ko")
        if not isinstance(pipeline_mechanic.value, Mapping):
            raise DataUnavailableError("Production duel rules require named tick-pipeline data")
        pipeline_id = pipeline_mechanic.value.get("pipeline_id")
        if not isinstance(pipeline_id, str):
            raise DataUnavailableError("tick.pipeline must define a pipeline_id")
        try:
            simultaneous_ko = TerminalStatus(outcome_mechanic.value)
        except ValueError as error:
            raise DataUnavailableError("death.simultaneous_ko must define a terminal payoff") from error
        return cls(
            pipeline_id,
            simultaneous_ko,
            maximum_ticks,
            switch_and_attack_same_tick,
            tuple(dict.fromkeys(pipeline_mechanic.source_ids + outcome_mechanic.source_ids)),
            "verified",
            attack_and_eat_same_tick,
            pipeline.priority_order,
        )

    def validate(self) -> None:
        if self.status != "verified" or not self.source_ids:
            raise VerifiedMechanicMissingError("Duel ordering rules have not been verified")
        if self.pipeline_id != "actions-before-new-impacts-v1":
            raise DataUnavailableError(f"Unsupported tick pipeline implementation {self.pipeline_id!r}")
        if self.simultaneous_ko not in {TerminalStatus.DRAW, TerminalStatus.PLAYER_WIN, TerminalStatus.OPPONENT_WIN}:
            raise DataUnavailableError("Duel rules do not define simultaneous-KO payoff")
        if self.maximum_ticks < 1:
            raise DataUnavailableError("Duel maximum tick count must be positive")
        if set(self.priority_order) != {"player", "opponent"}:
            raise DataUnavailableError("Duel rules must define player and opponent priority exactly once")


@dataclass(frozen=True, order=True)
class ScheduledHit:
    resolution_tick: int
    sequence: int
    source: str = field(compare=False)
    target: str = field(compare=False)
    damage_type: str = field(compare=False)
    amount: int = field(compare=False)
    weapon_id: int = field(compare=False)


@dataclass(frozen=True)
class DuelActor:
    hp: int
    max_hp: int
    active_weapon_id: int
    weapons: Mapping[int, AttackProfile]
    weapon_defence_bonuses: Mapping[int, Mapping[str, int]] = field(default_factory=dict)
    attack_ready_tick: int = 0
    eat_ready_tick: int = 0
    inventory: InventoryState = InventoryState(())
    consumed_items: tuple[str, ...] = ()
    defence_level: int = 1
    defence_boost: int = 0
    defence_prayer_multiplier: Fraction = Fraction(1)
    base_strength: int | None = None
    visible_strength: int | None = None
    combat_boost_decay_remaining: int | None = None
    drink_ready_tick: int = 0

    def __post_init__(self) -> None:
        if self.max_hp < 1 or self.active_weapon_id not in self.weapons:
            raise ValueError("Duel actor needs positive HP and an equipped weapon in its loadout")
        if self.defence_level < 1:
            raise ValueError("Duel actor defence level must be positive")
        if self.defence_boost < 0:
            raise ValueError("Duel actor defence boost cannot be negative")
        if self.weapon_defence_bonuses and self.active_weapon_id not in self.weapon_defence_bonuses:
            raise ValueError("Duel actor defence-bonus table must cover the active weapon")
        strength_fields = (self.base_strength, self.visible_strength, self.combat_boost_decay_remaining)
        if any(value is not None for value in strength_fields):
            if any(value is None for value in strength_fields):
                raise ValueError("Strength and boost-decay state must be configured together")
            if self.base_strength < 1 or self.visible_strength < 1 or self.combat_boost_decay_remaining < 1:
                raise ValueError("Strength and boost-decay state must be positive")
            if self.visible_strength < self.base_strength:
                raise ValueError("Drained Strength is outside the currently verified boost-only model")


@dataclass(frozen=True)
class PublicPendingHit:
    resolution_tick: int
    source: str
    target: str
    damage_type: str
    weapon_id: int


@dataclass(frozen=True)
class DuelView:
    tick: int
    own_hp: int
    opponent_hp: int
    own_weapon_id: int
    opponent_weapon_id: int
    own_attack_ready_tick: int
    opponent_attack_ready_tick: int
    own_eat_ready_tick: int
    own_inventory_id: str
    own_inventory_entries: tuple[InventoryEntry, ...]
    own_base_strength: int | None
    own_visible_strength: int | None
    own_drink_ready_tick: int
    distance: int
    pending_hits: tuple[PublicPendingHit, ...]


@dataclass(frozen=True)
class TickIntent:
    switch_to: int | None = None
    attack: bool = False
    eat: str | None = None
    drink: str | None = None


class DuelPolicy(Protocol):
    def choose(self, view: DuelView) -> TickIntent: ...


@dataclass(frozen=True)
class DuelState:
    tick: int
    player: DuelActor
    opponent: DuelActor
    distance: int
    pending_hits: tuple[ScheduledHit, ...] = ()
    terminal_status: TerminalStatus = TerminalStatus.ACTIVE
    history: tuple[str, ...] = ()


class AlwaysAttackPolicy:
    def choose(self, view: DuelView) -> TickIntent:
        return TickIntent(attack=view.tick >= view.own_attack_ready_tick)


@dataclass(frozen=True)
class TimedWeaponSwitchPolicy:
    primary_weapon_id: int
    ko_weapon_id: int
    switch_tick: int

    def choose(self, view: DuelView) -> TickIntent:
        desired = self.ko_weapon_id if view.tick >= self.switch_tick else self.primary_weapon_id
        return TickIntent(
            switch_to=desired if desired != view.own_weapon_id else None,
            attack=view.tick >= view.own_attack_ready_tick,
        )


@dataclass(frozen=True)
class RestrictedPolicy:
    """Explicit, human-implementable policy parameters suitable for grid search."""

    primary_weapon_id: int
    ko_weapon_id: int
    eat_threshold: int
    ko_threshold: int
    food_preference: tuple[str, ...] = ("anchovy_pizza", "swordfish")
    repot_when_boost_at_or_below: int | None = None

    def choose(self, view: DuelView) -> TickIntent:
        available = {entry.item_id for entry in view.own_inventory_entries}
        drink = None
        if (
            self.repot_when_boost_at_or_below is not None
            and view.own_base_strength is not None
            and view.own_visible_strength is not None
            and view.tick >= view.own_drink_ready_tick
            and "strength_potion" in available
            and view.own_visible_strength - view.own_base_strength <= self.repot_when_boost_at_or_below
        ):
            drink = "strength_potion"
        if view.own_hp <= self.eat_threshold and view.tick >= view.own_eat_ready_tick:
            food = next((item_id for item_id in self.food_preference if item_id in available), None)
            if food is not None:
                return TickIntent(eat=food, drink=drink)
        desired = self.ko_weapon_id if view.opponent_hp <= self.ko_threshold else self.primary_weapon_id
        return TickIntent(
            switch_to=desired if desired != view.own_weapon_id else None,
            attack=view.tick >= view.own_attack_ready_tick,
            drink=drink,
        )


@dataclass(frozen=True)
class ScriptedPolicy:
    intents: Mapping[int, TickIntent]

    def choose(self, view: DuelView) -> TickIntent:
        return self.intents.get(view.tick, TickIntent())


class DuelSimulator:
    """Pure logical-tick duel loop; no wall-clock timing or sleeps."""

    def __init__(
        self,
        rules: DuelRules,
        consumables: Mapping[str, Mapping[str, object]] | None = None,
        mechanics: MechanicRegistry | None = None,
    ):
        rules.validate()
        self.rules = rules
        self.consumables = dict(consumables or {})
        self.mechanics = mechanics

    def run(
        self,
        state: DuelState,
        player_policy: DuelPolicy,
        opponent_policy: DuelPolicy,
        *,
        seed: int,
    ) -> DuelState:
        rng = random.Random(seed)
        current = state
        sequence = max((event.sequence for event in current.pending_hits), default=-1) + 1
        while current.terminal_status is TerminalStatus.ACTIVE and current.tick < self.rules.maximum_ticks:
            current = self._resolve_due(current)
            current = self._terminal(current)
            if current.terminal_status is not TerminalStatus.ACTIVE:
                break

            player_intent = player_policy.choose(self._view(current, "player"))
            opponent_intent = opponent_policy.choose(self._view(current, "opponent"))
            current, sequence = self._apply_intents(current, player_intent, opponent_intent, rng, sequence)
            # New zero-delay melee hits and already-scheduled projectiles can
            # coexist here. The verified pipeline's PID priority decides their
            # serial damage resolution.
            current = self._resolve_due(current)
            current = self._terminal(current)
            if current.terminal_status is TerminalStatus.ACTIVE:
                current = replace(
                    current,
                    tick=current.tick + 1,
                    player=self._advance_boost_decay(current.player),
                    opponent=self._advance_boost_decay(current.opponent),
                )

        if current.terminal_status is TerminalStatus.ACTIVE:
            current = replace(current, terminal_status=TerminalStatus.TIMEOUT)
        return current

    def _view(self, state: DuelState, actor: str) -> DuelView:
        own = state.player if actor == "player" else state.opponent
        other = state.opponent if actor == "player" else state.player
        # Amount is intentionally absent: policies may observe a projectile but
        # cannot read a hidden future RNG result.
        public = tuple(
            PublicPendingHit(event.resolution_tick, event.source, event.target, event.damage_type, event.weapon_id)
            for event in state.pending_hits
        )
        return DuelView(
            tick=state.tick,
            own_hp=own.hp,
            opponent_hp=other.hp,
            own_weapon_id=own.active_weapon_id,
            opponent_weapon_id=other.active_weapon_id,
            own_attack_ready_tick=own.attack_ready_tick,
            opponent_attack_ready_tick=other.attack_ready_tick,
            own_eat_ready_tick=own.eat_ready_tick,
            own_inventory_id=own.inventory.canonical_id,
            own_inventory_entries=own.inventory.entries,
            own_base_strength=own.base_strength,
            own_visible_strength=own.visible_strength,
            own_drink_ready_tick=own.drink_ready_tick,
            distance=state.distance,
            pending_hits=public,
        )

    def _apply_intents(
        self,
        state: DuelState,
        player_intent: TickIntent,
        opponent_intent: TickIntent,
        rng: random.Random,
        sequence: int,
    ) -> tuple[DuelState, int]:
        player, player_switched = self._switch(state.player, player_intent.switch_to)
        opponent, opponent_switched = self._switch(state.opponent, opponent_intent.switch_to)
        history = list(state.history)
        if player_switched:
            history.append(f"{state.tick}:player:switch:{player.active_weapon_id}")
        if opponent_switched:
            history.append(f"{state.tick}:opponent:switch:{opponent.active_weapon_id}")
        pending = list(state.pending_hits)

        player, player_ate = self._eat(state.tick, "player", player, player_intent.eat, history)
        opponent, opponent_ate = self._eat(state.tick, "opponent", opponent, opponent_intent.eat, history)
        player = self._drink(state.tick, "player", player, player_intent.drink, history)
        opponent = self._drink(state.tick, "opponent", opponent, opponent_intent.drink, history)

        for actor_name, target_name, actor, intent, switched, ate in (
            ("player", "opponent", player, player_intent, player_switched, player_ate),
            ("opponent", "player", opponent, opponent_intent, opponent_switched, opponent_ate),
        ):
            if not intent.attack or state.tick < actor.attack_ready_tick:
                continue
            if ate and not self.rules.attack_and_eat_same_tick:
                continue
            if switched and not self.rules.switch_and_attack_same_tick:
                continue
            profile = self._profile_for_actor(actor)
            delay = profile.timing.impact_delay(state.distance)
            target = opponent if actor_name == "player" else player
            damage = self._roll_damage(profile, target, rng)
            pending.append(
                ScheduledHit(
                    state.tick + delay,
                    sequence,
                    actor_name,
                    target_name,
                    profile.damage_type,
                    damage,
                    profile.weapon_id,
                )
            )
            sequence += 1
            actor = replace(actor, attack_ready_tick=state.tick + profile.timing.cooldown_ticks)
            history.append(f"{state.tick}:{actor_name}:attack:{profile.weapon_id}:impact={state.tick + delay}")
            if actor_name == "player":
                player = actor
            else:
                opponent = actor
        return replace(
            state, player=player, opponent=opponent, pending_hits=tuple(pending), history=tuple(history)
        ), sequence

    def _drink(
        self,
        tick: int,
        actor_name: str,
        actor: DuelActor,
        consumable_id: str | None,
        history: list[str],
    ) -> DuelActor:
        if consumable_id is None or tick < actor.drink_ready_tick:
            return actor
        if consumable_id != "strength_potion":
            raise DataUnavailableError(f"Unsupported potion effect {consumable_id!r}")
        if actor.base_strength is None or actor.visible_strength is None:
            raise DataUnavailableError("Strength potion requires configured Strength state")
        if actor.visible_strength != actor.base_strength:
            if self.mechanics is None:
                raise VerifiedMechanicMissingError("Strength potion re-drink behavior is unavailable")
            # This mechanic intentionally remains absent from the production
            # ruleset until exact reboost application is independently proven.
            application = self.mechanics.require("potion.strength_reboost_application").value
            if application != "replace_visible_boost_with_static_cap":
                raise DataUnavailableError("Unsupported Strength potion reboost application")
        if self.mechanics is None:
            raise VerifiedMechanicMissingError("Strength potion formula mechanics are unavailable")
        inventory, transition = actor.inventory.consume(consumable_id, self.consumables)
        drink_delay = transition.get("drink_delay_ticks")
        attack_delay = transition.get("attack_delay_ticks")
        if not isinstance(drink_delay, int) or drink_delay < 0 or attack_delay != 0:
            raise DataUnavailableError("Strength potion has invalid verified timing")
        boost = self.mechanics.evaluate("strength_potion.boost", {"base_strength": actor.base_strength})
        if not isinstance(boost, int):
            boost = int(boost)
        result = replace(
            actor,
            inventory=inventory,
            visible_strength=actor.base_strength + boost,
            drink_ready_tick=tick + drink_delay,
            consumed_items=actor.consumed_items + (consumable_id,),
        )
        history.append(
            f"{tick}:{actor_name}:drink:{consumable_id}:strength={result.visible_strength}:"
            f"drink_ready={result.drink_ready_tick}"
        )
        return result

    def _profile_for_actor(self, actor: DuelActor) -> AttackProfile:
        profile = actor.weapons[actor.active_weapon_id]
        dynamic = profile.dynamic_melee
        if dynamic is None or actor.visible_strength is None:
            return profile
        if self.mechanics is None:
            raise VerifiedMechanicMissingError("Dynamic melee damage needs verified formula mechanics")
        effective_strength = self.mechanics.evaluate(
            "melee.effective_strength",
            {
                "strength_level": actor.visible_strength,
                "strength_boost": 0,
                "prayer_multiplier": dynamic.prayer_multiplier,
                "style_bonus": dynamic.style_bonus,
            },
        )
        max_hit = self.mechanics.evaluate(
            "melee.max_hit",
            {
                "effective_strength": effective_strength,
                "melee_strength_bonus": dynamic.melee_strength_bonus,
            },
        )
        return replace(profile, max_hit=int(max_hit))

    def _advance_boost_decay(self, actor: DuelActor) -> DuelActor:
        if actor.combat_boost_decay_remaining is None:
            return actor
        if actor.combat_boost_decay_remaining > 1:
            return replace(
                actor,
                combat_boost_decay_remaining=actor.combat_boost_decay_remaining - 1,
            )
        if self.mechanics is None:
            raise VerifiedMechanicMissingError("Combat boost decay interval is unavailable")
        interval = self.mechanics.require("boost.combat_decay_interval_ticks").value
        if not isinstance(interval, int) or interval < 1:
            raise DataUnavailableError("Combat boost decay interval is invalid")
        visible = actor.visible_strength
        if visible is None or actor.base_strength is None:
            raise DataUnavailableError("Combat boost decay has no Strength state")
        return replace(
            actor,
            visible_strength=max(actor.base_strength, visible - 1),
            combat_boost_decay_remaining=interval,
        )

    def _eat(
        self,
        tick: int,
        actor_name: str,
        actor: DuelActor,
        consumable_id: str | None,
        history: list[str],
    ) -> tuple[DuelActor, bool]:
        if consumable_id is None:
            return actor, False
        if tick < actor.eat_ready_tick:
            return actor, False
        inventory, transition = actor.inventory.consume(consumable_id, self.consumables)
        healing = transition.get("healing")
        eat_delay = transition.get("eat_delay_ticks")
        attack_delay = transition.get("attack_delay_ticks")
        if not all(isinstance(value, int) and value >= 0 for value in (healing, eat_delay, attack_delay)):
            raise DataUnavailableError(f"Consumable {consumable_id!r} lacks exact verified transition values")
        healed_hp = min(actor.max_hp, actor.hp + healing)
        result = replace(
            actor,
            hp=healed_hp,
            inventory=inventory,
            eat_ready_tick=tick + eat_delay,
            attack_ready_tick=max(tick, actor.attack_ready_tick) + attack_delay,
            consumed_items=actor.consumed_items + (consumable_id,),
        )
        history.append(
            f"{tick}:{actor_name}:eat:{consumable_id}:heal={healed_hp - actor.hp}:"
            f"eat_ready={result.eat_ready_tick}:attack_ready={result.attack_ready_tick}"
        )
        return result, True

    @staticmethod
    def _switch(actor: DuelActor, requested: int | None) -> tuple[DuelActor, bool]:
        if requested is None or requested == actor.active_weapon_id:
            return actor, False
        if requested not in actor.weapons:
            raise DataUnavailableError(f"Policy requested unavailable weapon {requested}")
        return replace(actor, active_weapon_id=requested), True

    def _hit_chance_against(self, profile: AttackProfile, target: DuelActor) -> Fraction:
        if self.mechanics is None or not target.weapon_defence_bonuses:
            return profile.hit_chance
        defence_bonuses = target.weapon_defence_bonuses.get(target.active_weapon_id)
        if defence_bonuses is None:
            return profile.hit_chance
        defence_bonus_name = "defence_ranged" if profile.damage_type == "ranged" else f"defence_{profile.damage_type}"
        if defence_bonus_name not in defence_bonuses:
            return profile.hit_chance
        target_profile = target.weapons[target.active_weapon_id]
        effective_defence = self.mechanics.evaluate(
            "player.effective_defence",
            {
                "defence_level": target.defence_level,
                "defence_boost": target.defence_boost,
                "prayer_multiplier": target.defence_prayer_multiplier,
                "style_bonus": target_profile.self_defence_style_bonus,
            },
        )
        defence_roll = self.mechanics.evaluate(
            "player.defence_roll",
            {
                "effective_defence": effective_defence,
                "defence_bonus": defence_bonuses[defence_bonus_name],
            },
        )
        return Fraction(
            self.mechanics.evaluate(
                "melee.accuracy",
                {
                    "attack_roll": profile.attack_roll,
                    "defence_roll": defence_roll,
                },
            )
        )

    def _roll_damage(self, profile: AttackProfile, target: DuelActor, rng: random.Random) -> int:
        if Fraction(rng.getrandbits(53), 1 << 53) >= self._hit_chance_against(profile, target):
            return 0
        damage = rng.randint(0, profile.max_hit)
        return 1 if profile.successful_zero_becomes_one and damage == 0 else damage

    def _resolve_due(self, state: DuelState) -> DuelState:
        due = (event for event in state.pending_hits if event.resolution_tick == state.tick)
        future = tuple(event for event in state.pending_hits if event.resolution_tick != state.tick)
        player_hp = state.player.hp
        opponent_hp = state.opponent.hp
        history = list(state.history)
        priority = {actor: index for index, actor in enumerate(self.rules.priority_order)}
        for event in sorted(due, key=lambda event: (priority.get(event.source, -1), event.sequence)):
            if event.source not in priority:
                raise DataUnavailableError(f"Scheduled hit has invalid source {event.source!r}")
            if event.source == "player" and player_hp <= 0:
                continue
            if event.source == "opponent" and opponent_hp <= 0:
                continue
            if event.target == "player":
                player_hp -= event.amount
            elif event.target == "opponent":
                opponent_hp -= event.amount
            else:
                raise DataUnavailableError(f"Scheduled hit has invalid target {event.target!r}")
            history.append(f"{state.tick}:{event.target}:damage:{event.amount}:weapon={event.weapon_id}")
        return replace(
            state,
            player=replace(state.player, hp=player_hp),
            opponent=replace(state.opponent, hp=opponent_hp),
            pending_hits=future,
            history=tuple(history),
        )

    def _terminal(self, state: DuelState) -> DuelState:
        player_dead = state.player.hp <= 0
        opponent_dead = state.opponent.hp <= 0
        if player_dead and opponent_dead:
            return replace(state, terminal_status=self.rules.simultaneous_ko)
        if player_dead:
            return replace(state, terminal_status=TerminalStatus.OPPONENT_WIN)
        if opponent_dead:
            return replace(state, terminal_status=TerminalStatus.PLAYER_WIN)
        return state
