"""Parse a pinned Wiki Strength potion page into a ``WikiPotionObservation`` without promoting it to verified
data.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import DataUnavailableError
from .wiki_items import parse_template


@dataclass(frozen=True)
class WikiPotionObservation:
    canonical_name: str
    item_id_by_doses: Mapping[int, int]
    maximum_doses: int
    free_to_play: bool
    source_ids: tuple[str, ...]
    status: str = "observed"


def observe_strength_potion(record: Mapping[str, Any]) -> WikiPotionObservation:
    content = record.get("content")
    if not isinstance(content, str):
        raise DataUnavailableError("Strength potion source is missing raw wikitext")
    item = parse_template(content, "Infobox Item")
    members = item.get("members", "").strip().casefold()
    if members not in {"yes", "no"}:
        raise DataUnavailableError("Strength potion source has no exact members claim")
    doses: dict[int, int] = {}
    for key, name in item.items():
        match = re.fullmatch(r"name(\d+)", key)
        if not match:
            continue
        version = match.group(1)
        dose_match = re.fullmatch(r"Strength potion\((\d)\)", name.strip(), re.IGNORECASE)
        item_id = item.get(f"id{version}")
        if dose_match and item_id and item_id.strip().isdigit():
            doses[int(dose_match.group(1))] = int(item_id.strip())
    if set(doses) != {1, 2, 3, 4}:
        raise DataUnavailableError(f"Strength potion source does not define all four doses: {doses}")
    if not re.search(
        r"3\s*\+\s*10%.*Strength level.*rounded down",
        content,
        re.IGNORECASE | re.DOTALL,
    ):
        raise DataUnavailableError("Strength potion source lacks its boost formula statement")
    return WikiPotionObservation(
        canonical_name="Strength potion",
        item_id_by_doses=dict(sorted(doses.items())),
        maximum_doses=4,
        free_to_play=members == "no",
        source_ids=(str(record.get("source_id", "")),),
    )
