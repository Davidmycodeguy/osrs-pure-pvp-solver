"""Build the verified Strength potion consumable document (four doses down to an empty vial) from the archived
Wiki page plus review decisions, requiring the pinned evidence sources.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import DataUnavailableError
from .legality import F2P_STANDARD_WORLD_SCOPE
from .wiki_potions import observe_strength_potion


def build_verified_potion_documents(
    source_archive: str | Path,
    decision_document: Mapping[str, Any],
    available_source_ids: set[str],
) -> list[dict[str, Any]]:
    archive = Path(source_archive).resolve()
    result: list[dict[str, Any]] = []
    for decision in decision_document.get("potions", []):
        source_path = (archive / str(decision["source_file"])).resolve()
        if source_path.parent != archive:
            raise DataUnavailableError("Potion decision source escapes the source archive")
        try:
            source = json.loads(source_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as error:
            raise DataUnavailableError(f"Cannot read potion source {source_path}") from error
        observation = observe_strength_potion(source)
        if str(decision.get("consumable_id")) != "strength_potion":
            raise DataUnavailableError("Strength potion decision has the wrong canonical ID")
        if decision.get("availability_scope") != F2P_STANDARD_WORLD_SCOPE:
            raise DataUnavailableError("Strength potion is not approved for the F2P standard-world scope")
        expected_ids = {int(key): int(value) for key, value in decision.get("expected_item_id_by_doses", {}).items()}
        if expected_ids != observation.item_id_by_doses:
            raise DataUnavailableError(
                f"Strength potion item IDs disagree: expected {expected_ids}, observed {observation.item_id_by_doses}"
            )
        if not observation.free_to_play:
            raise DataUnavailableError("Strength potion is not observed as F2P")
        evidence = set(observation.source_ids)
        evidence.update(map(str, decision.get("source_ids", [])))
        unknown = evidence - available_source_ids
        if unknown:
            raise DataUnavailableError(f"Potion verification cites unavailable sources: {sorted(unknown)}")
        required = {"osrs-wiki:18169:15183998", "osrs-wiki:35852:15214505", "osrs-wiki:28248:15315536"}
        if not required.issubset(evidence):
            raise DataUnavailableError(f"Potion verification is missing evidence: {sorted(required - evidence)}")
        transitions: dict[str, dict[str, object]] = {}
        for doses in range(4, 0, -1):
            if doses > 1:
                next_item_id = "strength_potion"
                next_state = f"{doses - 1}_dose"
            else:
                next_item_id = "empty_vial"
                next_state = "empty"
            transitions[f"{doses}_dose"] = {
                "next_item_id": next_item_id,
                "next_state": next_state,
                "drink_delay_ticks": 3,
                "attack_delay_ticks": 0,
                "effect": {"kind": "strength_boost", "formula_mechanic": "strength_potion.boost"},
            }
        result.append(
            {
                "consumable_id": "strength_potion",
                "kind": "potion",
                "name": observation.canonical_name,
                "item_id_by_doses": {str(key): value for key, value in observation.item_id_by_doses.items()},
                "initial_state": "4_dose",
                "transitions": transitions,
                "source_ids": sorted(evidence),
                "status": "verified",
                "availability_scope": F2P_STANDARD_WORLD_SCOPE,
            }
        )
    return result
