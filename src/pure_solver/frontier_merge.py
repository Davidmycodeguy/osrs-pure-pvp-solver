"""Merge per-shard ``offense-frontier`` documents whose scope, target, assumptions and verification metadata
match into one deduplicated top-N report.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import Any

from .canonical import canonical_hash
from .errors import MechanicConflictError


def _fraction(raw: Mapping[str, Any]) -> Fraction:
    return Fraction(int(raw["numerator"]), int(raw["denominator"]))


def _overall_key(candidate: Mapping[str, Any]) -> tuple[object, ...]:
    inventory = candidate["inventory_frontier"]
    return (
        _fraction(candidate["primary"]["expected_damage_per_tick"]),
        int(candidate["primary"]["max_hit"]),
        _fraction(candidate["ko"]["expected_damage_per_tick"]),
        int(candidate["ko"]["max_hit"]),
        int(inventory["best_total_healing"]["total_healing"]),
        int(inventory["best_total_actions"]["total_actions"]),
    )


def _ko_key(candidate: Mapping[str, Any]) -> tuple[object, ...]:
    inventory = candidate["inventory_frontier"]
    return (
        int(candidate["ko"]["max_hit"]),
        _fraction(candidate["primary"]["expected_damage_per_tick"]),
        _fraction(candidate["ko"]["expected_damage_per_tick"]),
        int(inventory["best_total_healing"]["total_healing"]),
        int(inventory["best_total_actions"]["total_actions"]),
    )


def _deduplicated(candidates: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return list({canonical_hash(candidate): candidate for candidate in candidates}.values())


def merge_offense_frontiers(
    documents: Sequence[Mapping[str, Any]],
    *,
    top: int = 10,
) -> Mapping[str, Any]:
    if not documents or top < 1:
        raise ValueError("Frontier merge needs documents and top >= 1")
    reference = documents[0]
    invariant_fields = ("scope", "account_mode", "verification", "reproducibility", "target", "assumptions")
    for document in documents[1:]:
        for field in invariant_fields:
            if document.get(field) != reference.get(field):
                raise MechanicConflictError(f"Frontier shards disagree on {field!r}")

    overall = _deduplicated([candidate for document in documents for candidate in document.get("top_overall", ())])
    ko = _deduplicated([candidate for document in documents for candidate in document.get("top_by_ko_max_hit", ())])
    by_hitpoints: dict[str, Mapping[str, Any]] = {}
    by_combat: dict[str, Mapping[str, Any]] = {}
    for document in documents:
        for hitpoints, candidate in document.get("best_by_hitpoints", {}).items():
            if hitpoints not in by_hitpoints or _overall_key(candidate) > _overall_key(by_hitpoints[hitpoints]):
                by_hitpoints[hitpoints] = candidate
        for combat, candidate in document.get("best_by_combat_level", {}).items():
            if combat not in by_combat or _overall_key(candidate) > _overall_key(by_combat[combat]):
                by_combat[combat] = candidate

    searches = [document.get("search", {}) for document in documents]
    prayer_levels = sorted({int(level) for search in searches for level in search.get("prayer_levels_considered", ())})
    cache_names = sorted({name for search in searches for name in search.get("cache_sizes", {})})
    return {
        "scope": reference["scope"],
        "account_mode": reference["account_mode"],
        "verification": reference["verification"],
        "reproducibility": reference["reproducibility"],
        "target": reference["target"],
        "assumptions": reference["assumptions"],
        "search": {
            "shard_count": len(documents),
            "generated_accounts": sum(int(search.get("generated_accounts", 0)) for search in searches),
            "achievable_accounts": sum(int(search.get("achievable_accounts", 0)) for search in searches),
            "unachievable_accounts_rejected": sum(
                int(search.get("unachievable_accounts_rejected", 0)) for search in searches
            ),
            "pareto_accounts": sum(int(search.get("pareto_accounts", 0)) for search in searches),
            "dominated_accounts_pruned": sum(int(search.get("dominated_accounts_pruned", 0)) for search in searches),
            "evaluated_candidates": sum(int(search.get("evaluated_candidates", 0)) for search in searches),
            "top_limit": top,
            "prayer_levels_considered": prayer_levels,
            "cache_sizes_across_shards": {
                name: sum(int(search.get("cache_sizes", {}).get(name, 0)) for search in searches)
                for name in cache_names
            },
        },
        "top_overall": sorted(overall, key=_overall_key, reverse=True)[:top],
        "top_by_ko_max_hit": sorted(ko, key=_ko_key, reverse=True)[:top],
        "best_by_hitpoints": dict(sorted(by_hitpoints.items(), key=lambda item: int(item[0]))),
        "best_by_combat_level": dict(sorted(by_combat.items(), key=lambda item: int(item[0]))),
    }
