"""Add verified equipment to a ruleset from pinned OSRS Wiki pages in one pass.

For every page title: fetch and archive the current revision (or reuse the archive),
register its ``osrs-wiki:<pageid>:<revid>`` source in ``mechanics.json``, parse the
page, write a verification decision that cites that source for every parser gap,
rebuild ``items.json`` and re-verify the source archive.  Requirements are never
hand-written: a page whose lead the parser cannot read is reported and skipped.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import DataUnavailableError
from .item_verification import build_verified_item_documents
from .legality import F2P_STANDARD_WORLD_SCOPE
from .ruleset import load_ruleset
from .sources import fetch_wiki_revision, write_source_record
from .wiki_items import WikiItemObservation, observe_equipment

METAL_TIERS = ("Bronze", "Iron", "Steel", "Black", "Mithril", "Adamant", "Rune")
METAL_PIECES = ("full helm", "med helm", "platebody", "chainbody", "platelegs", "plateskirt", "kiteshield", "sq shield")
DEFENCE_ARMOUR_TITLES: tuple[str, ...] = tuple(f"{tier} {piece}" for tier in METAL_TIERS for piece in METAL_PIECES) + (
    "Hardleather body",
    "Studded body",
    "Studded chaps",
    "Green d'hide body",
    "Leather cowl",
    "Leather gloves",
)
STAFF_TITLES: tuple[str, ...] = ("Staff of air", "Staff of water", "Staff of earth", "Staff of fire")
DEFAULT_TITLES: tuple[str, ...] = DEFENCE_ARMOUR_TITLES + STAFF_TITLES

# Staves bash with crush; the spell side is modelled by the solver from the spell table.
STAFF_STYLES = ("accurate_crush", "aggressive_crush", "defensive_crush")
# Quest gates stated in the page lead; the parser reads skill levels only.
QUEST_REQUIREMENTS: dict[int, tuple[str, ...]] = {
    1127: ("Dragon Slayer I",),  # Rune platebody
    1135: ("Dragon Slayer I",),  # Green d'hide body
}
_QUEST_CUE = re.compile(r"Dragon Slayer I\b", re.IGNORECASE)


def archive_slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.casefold().replace("'", "")).strip("-")


@dataclass(frozen=True)
class AddedItem:
    title: str
    item_id: int
    slot: str
    requirements: dict[str, int]
    quest_requirements: tuple[str, ...]
    source_id: str
    outcome: str


def _source_entry(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "content_sha256": record["content_sha256"],
        "retrieved_at": record["retrieved_at"],
        "revision": record["revision"],
        "source_id": record["source_id"],
        "url": record["url"],
    }


def _decision(observation: WikiItemObservation, source_file: str, quests: tuple[str, ...]) -> dict[str, Any]:
    source_id = observation.source_ids[0]
    is_staff = observation.slot in {"weapon", "2h"}
    return {
        "ammo_ids": [],
        "attack_styles": list(STAFF_STYLES) if is_staff else [],
        "availability_scope": F2P_STANDARD_WORLD_SCOPE,
        "evidence_by_gap": {gap: [source_id] for gap in observation.verification_gaps},
        "item_id": observation.item_id,
        "mechanic_flags": [],
        "obtainable": True,
        "quest_requirements": list(quests),
        "requirements": dict(observation.requirements),
        "source_file": source_file,
        "spell_ids": [],
        "two_handed": False,
        "weapon_type": "staff" if is_staff else None,
    }


def _load_record(title: str, archive: Path, fetch: bool) -> tuple[dict[str, Any], Path, str]:
    path = archive / f"{archive_slug(title)}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")), path, "archived"
    if not fetch:
        raise DataUnavailableError(f"No archived page for {title!r} and fetching is disabled")
    record = fetch_wiki_revision(title)
    write_source_record(record, path)
    return record, path, "fetched"


def _quest_gate(observation: WikiItemObservation, record: dict[str, Any]) -> tuple[str, ...]:
    quests = QUEST_REQUIREMENTS.get(observation.item_id, ())
    if quests and not _QUEST_CUE.search(record.get("content", "")):
        raise DataUnavailableError(f"{observation.name!r}: expected the page to mention {quests[0]!r}")
    return quests


def add_items(
    ruleset_dir: str | Path, titles: Iterable[str] = DEFAULT_TITLES, *, fetch: bool = True
) -> list[AddedItem]:
    """Archive, register, decide, rebuild and verify.  Returns one row per title."""
    ruleset_dir = Path(ruleset_dir)
    ruleset = load_ruleset(ruleset_dir)
    if ruleset.source_archive is None:
        raise DataUnavailableError("Ruleset has no source archive")
    archive = Path(ruleset.source_archive)
    mechanics_path = ruleset_dir / "mechanics.json"
    decisions_path = ruleset_dir / "item-verification.json"
    mechanics = json.loads(mechanics_path.read_text(encoding="utf-8"))
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    known_sources = {entry["source_id"] for entry in mechanics["sources"]}
    decided = {row["item_id"]: row for row in decisions["items"]}
    rows: list[AddedItem] = []
    for title in titles:
        try:
            record, path, how = _load_record(title, archive, fetch)
            observation = observe_equipment(record)
            quests = _quest_gate(observation, record)
        except DataUnavailableError as error:
            rows.append(AddedItem(title, 0, "?", {}, (), "", f"skipped: {error}"))
            continue
        if observation.item_id in decided:
            rows.append(
                AddedItem(
                    title,
                    observation.item_id,
                    observation.slot,
                    dict(observation.requirements),
                    quests,
                    record["source_id"],
                    "already verified",
                )
            )
            continue
        if record["source_id"] not in known_sources:
            mechanics["sources"].append(_source_entry(record))
            known_sources.add(record["source_id"])
        decision = _decision(observation, path.name, quests)
        decisions["items"].append(decision)
        decided[observation.item_id] = decision
        rows.append(
            AddedItem(
                title,
                observation.item_id,
                observation.slot,
                dict(observation.requirements),
                quests,
                record["source_id"],
                f"added ({how})",
            )
        )
    mechanics_path.write_text(json.dumps(mechanics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    decisions_path.write_text(json.dumps(decisions, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rebuilt = load_ruleset(ruleset_dir)
    documents = build_verified_item_documents(archive, decisions, set(rebuilt.mechanics.source_revisions))
    (ruleset_dir / "items.json").write_text(json.dumps(documents, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    load_ruleset(ruleset_dir).verify_source_archive()
    return rows


def format_table(rows: Iterable[AddedItem]) -> str:
    lines = [f"{'title':22s} {'id':>6s} {'slot':7s} {'requirements':28s} {'quests':16s} outcome"]
    for row in rows:
        requirements = ", ".join(f"{skill} {level}" for skill, level in sorted(row.requirements.items())) or "-"
        quests = ", ".join(row.quest_requirements) or "-"
        lines.append(f"{row.title:22s} {row.item_id:>6d} {row.slot:7s} {requirements:28s} {quests:16s} {row.outcome}")
    return "\n".join(lines)
