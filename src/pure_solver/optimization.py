"""Enumerate restricted duel policies over a grid of eat/KO thresholds, food preferences and re-pot thresholds,
and rank them by an evaluator objective with deterministic tie-breaking.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from itertools import product

from .duel import RestrictedPolicy


@dataclass(frozen=True)
class PolicyEvaluation:
    policy: RestrictedPolicy
    objective: float


def enumerate_restricted_policies(
    primary_weapon_id: int,
    ko_weapon_id: int,
    *,
    eat_thresholds: Iterable[int],
    ko_thresholds: Iterable[int],
    food_preferences: Iterable[tuple[str, ...]] = (("anchovy_pizza", "swordfish"),),
    repot_thresholds: Iterable[int | None] = (None,),
) -> tuple[RestrictedPolicy, ...]:
    policies = {
        RestrictedPolicy(primary_weapon_id, ko_weapon_id, eat, ko, preference, repot)
        for eat, ko, preference, repot in product(eat_thresholds, ko_thresholds, food_preferences, repot_thresholds)
    }
    return tuple(
        sorted(
            policies,
            key=lambda policy: (
                policy.eat_threshold,
                policy.ko_threshold,
                policy.food_preference,
                (policy.repot_when_boost_at_or_below is None, policy.repot_when_boost_at_or_below),
                policy.primary_weapon_id,
                policy.ko_weapon_id,
            ),
        )
    )


def optimize_restricted_policy(
    policies: Iterable[RestrictedPolicy],
    evaluator: Callable[[RestrictedPolicy], float],
) -> tuple[PolicyEvaluation, tuple[PolicyEvaluation, ...]]:
    evaluations = tuple(PolicyEvaluation(policy, float(evaluator(policy))) for policy in policies)
    if not evaluations:
        raise ValueError("Policy optimization requires at least one candidate")
    ranked = tuple(
        sorted(
            evaluations,
            key=lambda item: (
                -item.objective,
                item.policy.eat_threshold,
                item.policy.ko_threshold,
                item.policy.food_preference,
                (item.policy.repot_when_boost_at_or_below is None, item.policy.repot_when_boost_at_or_below),
            ),
        )
    )
    return ranked[0], ranked
