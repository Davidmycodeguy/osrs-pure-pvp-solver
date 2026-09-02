"""Parse a pinned Wiki food page into a ``WikiConsumableObservation`` (healing and item-state chain per bite)
without promoting it to verified data.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from .errors import DataUnavailableError
from .wiki_items import _yes_no, parse_template


@dataclass(frozen=True)
class WikiConsumableObservation:
    name: str
    item_ids: tuple[int, ...]
    free_to_play: bool
    healing_by_state: Mapping[str, int]
    next_state_by_state: Mapping[str, str | None]
    source_ids: tuple[str, ...]
    status: str
    verification_gaps: tuple[str, ...]

    def to_document(self) -> dict[str, Any]:
        return asdict(self)


def _ids(fields: Mapping[str, str]) -> tuple[int, ...]:
    values: list[tuple[int, int]] = []
    if fields.get("id"):
        values.append((1, int(fields["id"].replace(",", "").strip())))
    for key, value in fields.items():
        match = re.fullmatch(r"id(\d+)", key)
        if match and value.strip().isdigit():
            values.append((int(match.group(1)), int(value.strip())))
    return tuple(value for _, value in sorted(set(values)))


def observe_consumable(record: Mapping[str, Any]) -> WikiConsumableObservation:
    content = record.get("content")
    if not isinstance(content, str):
        raise DataUnavailableError("Wiki source record is missing raw wikitext")
    item = parse_template(content, "Infobox Item")
    name = item.get("name") or item.get("name1")
    if not name:
        raise DataUnavailableError("Consumable page has no item name")
    item_ids = _ids(item)
    if not item_ids:
        raise DataUnavailableError("Consumable page has no exact item ID")
    if "members" not in item:
        raise DataUnavailableError("Consumable page has no exact members claim")
    source_id = record.get("source_id")
    if not isinstance(source_id, str) or not source_id.strip():
        raise DataUnavailableError("Wiki source record is missing its source ID")

    total_patterns = (
        r"restores\s+(\d+)\s+\[\[Hitpoints\]\]",
        r"heals\s+(\d+)\s+hitpoints",
        r"restore\s+(\d+)\s+\[\[hitpoints\]\]",
    )
    total_match = next(
        (match for pattern in total_patterns if (match := re.search(pattern, content, re.IGNORECASE))),
        None,
    )
    bites_match = re.search(r"(\d+)\s+bites?\s+each\s+healing\s+for\s+(\d+)", content, re.IGNORECASE)
    if not total_match:
        raise DataUnavailableError("Consumable page has no machine-readable healing statement")
    total = int(total_match.group(1))
    if bites_match:
        bites, each = int(bites_match.group(1)), int(bites_match.group(2))
        if bites * each != total:
            raise DataUnavailableError("Consumable healing statement is internally contradictory")
        if bites == 2:
            states = {"full": each, "half": each}
            next_states = {"full": "half", "half": None}
        else:
            states = {f"bite_{index + 1}": each for index in range(bites)}
            next_states = {
                f"bite_{index + 1}": f"bite_{index + 2}" if index + 1 < bites else None for index in range(bites)
            }
    else:
        states = {"whole": total}
        next_states = {"whole": None}
    return WikiConsumableObservation(
        name=name.strip(),
        item_ids=item_ids,
        free_to_play=not _yes_no(item["members"], "members"),
        healing_by_state=states,
        next_state_by_state=next_states,
        source_ids=(source_id,),
        status="observed",
        verification_gaps=(
            "eat_delay_ticks",
            "attack_delay_ticks",
            "state_transition_order",
            "obtainability",
            "availability_scope",
        ),
    )
