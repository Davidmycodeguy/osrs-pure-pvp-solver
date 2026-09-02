"""Build verified food documents for a ruleset from archived Wiki pages plus review decisions, rejecting any
decision whose identity, scope, evidence or transition graph disagrees with the pinned source.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import DataUnavailableError
from .legality import F2P_STANDARD_WORLD_SCOPE
from .wiki_consumables import observe_consumable


def build_verified_consumable_documents(
    source_archive: str | Path,
    decision_document: Mapping[str, Any],
    available_source_ids: set[str],
) -> list[dict[str, Any]]:
    source_archive = Path(source_archive).resolve()
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for decision in decision_document.get("consumables", []):
        source_path = (source_archive / str(decision["source_file"])).resolve()
        if source_path.parent != source_archive:
            raise DataUnavailableError("Consumable decision source file escapes the source archive")
        try:
            source = json.loads(source_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as error:
            raise DataUnavailableError(f"Cannot read consumable source record {source_path}") from error
        observation = observe_consumable(source)
        consumable_id = str(decision["consumable_id"])
        if consumable_id in seen_ids:
            raise DataUnavailableError(f"Consumable decisions duplicate ID {consumable_id!r}")
        seen_ids.add(consumable_id)
        if decision.get("availability_scope") != F2P_STANDARD_WORLD_SCOPE:
            raise DataUnavailableError(f"Consumable {consumable_id!r} is not approved for the F2P standard-world scope")
        if not observation.free_to_play:
            raise DataUnavailableError(f"Consumable {observation.name!r} is not source-observed as F2P")
        canonical_id = re.sub(r"[^a-z0-9]+", "_", observation.name.casefold()).strip("_")
        if consumable_id != canonical_id:
            raise DataUnavailableError(
                f"Consumable ID {consumable_id!r} does not match source-derived identity {canonical_id!r}"
            )
        expected_name = str(decision.get("expected_name", ""))
        expected_item_ids = tuple(map(int, decision.get("expected_item_ids", [])))
        if expected_name != observation.name or expected_item_ids != observation.item_ids:
            raise DataUnavailableError(
                f"Consumable identity mismatch: decision expected {expected_name!r}/{expected_item_ids}, "
                f"source observed {observation.name!r}/{observation.item_ids}"
            )
        evidence_by_gap = {
            str(gap): tuple(map(str, source_ids)) for gap, source_ids in decision.get("evidence_by_gap", {}).items()
        }
        missing = set(observation.verification_gaps) - set(evidence_by_gap)
        if missing:
            raise DataUnavailableError(f"Consumable {observation.name!r} lacks evidence for {sorted(missing)}")
        source_ids = set(observation.source_ids)
        for gap in observation.verification_gaps:
            evidence = evidence_by_gap[gap]
            if not evidence:
                raise DataUnavailableError(f"Consumable gap {gap!r} has no evidence")
            source_ids.update(evidence)
        unknown = source_ids - available_source_ids
        if unknown:
            raise DataUnavailableError(f"Consumable verification cites unavailable sources: {sorted(unknown)}")

        transitions = decision.get("transitions")
        if not isinstance(transitions, Mapping) or set(transitions) != set(observation.healing_by_state):
            raise DataUnavailableError(
                f"Consumable transition states disagree with source observation for {observation.name!r}"
            )
        for state, healing in observation.healing_by_state.items():
            transition = transitions[state]
            if not isinstance(transition, Mapping) or int(transition.get("healing", -1)) != healing:
                raise DataUnavailableError(f"Consumable healing disagrees in state {state!r}")
            if transition.get("next_state") != observation.next_state_by_state[state]:
                raise DataUnavailableError(
                    f"Consumable transition order disagrees in state {state!r}: "
                    f"expected {observation.next_state_by_state[state]!r}"
                )
            for timing in ("eat_delay_ticks", "attack_delay_ticks"):
                if not isinstance(transition.get(timing), int) or transition[timing] < 0:
                    raise DataUnavailableError(f"Consumable state {state!r} lacks exact {timing}")
        result.append(
            {
                "consumable_id": consumable_id,
                "kind": "food",
                "name": observation.name,
                "item_ids": list(observation.item_ids),
                "transitions": {str(state): dict(transition) for state, transition in transitions.items()},
                "source_ids": sorted(source_ids),
                "status": "verified",
                "availability_scope": F2P_STANDARD_WORLD_SCOPE,
            }
        )
    result.sort(key=lambda item: item["consumable_id"])
    return result
