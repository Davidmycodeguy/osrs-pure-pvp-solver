"""Promote Wiki item observations into verified item documents (or explicitly provisional ``wiki_trusted`` ones)
using review decisions, refusing any decision whose source is missing from the archive or whose scope is not
the F2P standard world.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import DataUnavailableError
from .legality import F2P_STANDARD_WORLD_SCOPE, EquipmentItem
from .wiki_items import WikiItemObservation, observe_equipment

_MELEE_STYLE_FAMILIES: dict[str, tuple[str, ...]] = {
    "stab": ("accurate_stab", "aggressive_stab", "controlled_stab", "defensive_stab"),
    "slash": ("accurate_slash", "aggressive_slash", "controlled_slash", "defensive_slash"),
    "crush": ("accurate_crush", "aggressive_crush", "controlled_crush", "defensive_crush"),
}


def infer_attack_styles(combat_style: str | None) -> tuple[str, ...]:
    lowered = combat_style.casefold() if combat_style else ""
    for keyword, styles in _MELEE_STYLE_FAMILIES.items():
        if keyword in lowered:
            return styles
    if "ranged" in lowered or "range" in lowered:
        return ("rapid_ranged",)
    return ()


def observation_to_provisional_item_document(observation: WikiItemObservation) -> dict[str, Any]:
    """Build an intentionally provisional item row from raw wiki observations.

    These rows do not represent full verification; they only carry parsed
    observations and their source-of-truth link.
    """
    return {
        "item_id": observation.item_id,
        "name": observation.name,
        "free_to_play": observation.free_to_play,
        "members": observation.members,
        "obtainable": observation.equipable,
        "slot": observation.slot,
        "requirements": dict(observation.requirements),
        "quest_requirements": tuple(),
        "bonuses": dict(observation.bonuses),
        "two_handed": False,
        "weapon_type": None,
        "attack_speed": observation.attack_speed,
        "attack_range": observation.attack_range,
        "attack_styles": tuple(infer_attack_styles(observation.combat_style)),
        "ammo_ids": tuple(),
        "spell_ids": tuple(),
        "mechanic_flags": tuple(),
        "source_ids": tuple(observation.source_ids),
        "status": "wiki_trusted",
        "availability_scope": F2P_STANDARD_WORLD_SCOPE,
    }


def build_wiki_trusted_item_documents(
    source_archive: str | Path, *, include_environment_scoped: bool = False
) -> list[dict[str, Any]]:
    source_archive = Path(source_archive)
    if not source_archive.exists():
        raise DataUnavailableError(f"Source archive path does not exist: {source_archive}")
    documents: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for path in sorted(source_archive.glob("*.json")):
        try:
            source = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        try:
            observation = observe_equipment(source)
        except DataUnavailableError:
            continue
        if not include_environment_scoped and observation.environment_scope is not None:
            continue
        if not observation.free_to_play or observation.members or not observation.equipable:
            continue
        if observation.item_id in seen_ids:
            continue
        if not observation.source_ids:
            continue
        if not all(isinstance(value, str) for value in observation.source_ids):
            continue
        if observation.item_id == 0:
            continue
        documents.append(observation_to_provisional_item_document(observation))
        seen_ids.add(observation.item_id)
    return documents


@dataclass(frozen=True)
class VerificationDecision:
    item_id: int
    source_file: str
    obtainable: bool
    availability_scope: str
    requirements: Mapping[str, int]
    quest_requirements: tuple[str, ...]
    two_handed: bool
    weapon_type: str | None
    attack_styles: tuple[str, ...]
    ammo_ids: tuple[int, ...]
    spell_ids: tuple[str, ...]
    mechanic_flags: tuple[str, ...]
    evidence_by_gap: Mapping[str, tuple[str, ...]]

    @classmethod
    def from_document(cls, raw: Mapping[str, Any]) -> VerificationDecision:
        required = {
            "item_id",
            "source_file",
            "obtainable",
            "availability_scope",
            "requirements",
            "quest_requirements",
            "two_handed",
            "attack_styles",
            "ammo_ids",
            "spell_ids",
            "mechanic_flags",
            "evidence_by_gap",
        }
        missing = required - set(raw)
        if missing:
            raise DataUnavailableError(f"Item verification decision is missing fields: {sorted(missing)}")
        if isinstance(raw["item_id"], bool) or not isinstance(raw["item_id"], int) or raw["item_id"] <= 0:
            raise DataUnavailableError("Item verification decision item_id must be a positive integer")
        if not isinstance(raw["source_file"], str) or not raw["source_file"].strip():
            raise DataUnavailableError("Item verification decision source_file must be a non-empty string")
        if not isinstance(raw["obtainable"], bool) or not isinstance(raw["two_handed"], bool):
            raise DataUnavailableError("Item verification decision booleans must be exact booleans")
        if not isinstance(raw["requirements"], Mapping) or not isinstance(raw["evidence_by_gap"], Mapping):
            raise DataUnavailableError("Item verification requirements and evidence must be mappings")
        return cls(
            item_id=raw["item_id"],
            source_file=raw["source_file"].strip(),
            obtainable=raw["obtainable"],
            availability_scope=str(raw["availability_scope"]),
            requirements={str(key): int(value) for key, value in raw.get("requirements", {}).items()},
            quest_requirements=tuple(sorted(map(str, raw.get("quest_requirements", [])))),
            two_handed=bool(raw.get("two_handed", False)),
            weapon_type=raw.get("weapon_type") and str(raw["weapon_type"]),
            attack_styles=tuple(map(str, raw.get("attack_styles", []))),
            ammo_ids=tuple(map(int, raw.get("ammo_ids", []))),
            spell_ids=tuple(map(str, raw.get("spell_ids", []))),
            mechanic_flags=tuple(sorted(map(str, raw.get("mechanic_flags", [])))),
            evidence_by_gap={
                str(gap): tuple(map(str, source_ids)) for gap, source_ids in raw.get("evidence_by_gap", {}).items()
            },
        )


def promote_observation(
    observation: WikiItemObservation,
    decision: VerificationDecision,
    available_source_ids: set[str],
) -> EquipmentItem:
    if decision.item_id != observation.item_id:
        raise DataUnavailableError("Verification decision item ID does not match its parsed source")
    if decision.availability_scope != F2P_STANDARD_WORLD_SCOPE:
        raise DataUnavailableError(f"Item {observation.name!r} is not approved for the F2P standard-world scope")
    if observation.environment_scope is not None:
        raise DataUnavailableError(f"Item {observation.name!r} is explicitly scoped to {observation.environment_scope}")
    missing_evidence = set(observation.verification_gaps) - set(decision.evidence_by_gap)
    if missing_evidence:
        raise DataUnavailableError(
            f"Item {observation.name!r} cannot be promoted; evidence is missing for {sorted(missing_evidence)}"
        )
    cited_sources: set[str] = set(observation.source_ids)
    for gap in observation.verification_gaps:
        evidence = decision.evidence_by_gap[gap]
        if not evidence:
            raise DataUnavailableError(f"Item verification gap {gap!r} has an empty evidence set")
        cited_sources.update(evidence)
    unknown = cited_sources - available_source_ids
    if unknown:
        raise DataUnavailableError(f"Item verification cites unavailable sources: {sorted(unknown)}")
    if dict(decision.requirements) != dict(observation.requirements):
        raise DataUnavailableError(f"Verified skill requirements disagree with parsed source for {observation.name!r}")
    if not observation.free_to_play or observation.members or not observation.equipable:
        raise DataUnavailableError(f"Item {observation.name!r} is not source-observed as equippable F2P gear")
    return EquipmentItem(
        item_id=observation.item_id,
        name=observation.name,
        free_to_play=True,
        members=False,
        obtainable=decision.obtainable,
        slot=observation.slot,
        requirements=dict(decision.requirements),
        quest_requirements=decision.quest_requirements,
        bonuses=dict(observation.bonuses),
        two_handed=decision.two_handed,
        weapon_type=decision.weapon_type,
        attack_speed=observation.attack_speed,
        attack_range=observation.attack_range,
        attack_styles=decision.attack_styles,
        ammo_ids=decision.ammo_ids,
        spell_ids=decision.spell_ids,
        mechanic_flags=decision.mechanic_flags,
        source_ids=tuple(sorted(cited_sources)),
        status="verified",
        availability_scope=decision.availability_scope,
    )


def build_verified_item_documents(
    source_archive: str | Path,
    decision_document: Mapping[str, Any],
    available_source_ids: set[str],
) -> list[dict[str, Any]]:
    source_archive = Path(source_archive)
    documents: list[dict[str, Any]] = []
    seen_item_ids: set[int] = set()
    for raw in decision_document.get("items", []):
        decision = VerificationDecision.from_document(raw)
        if decision.item_id in seen_item_ids:
            raise DataUnavailableError(f"Verification decisions duplicate item ID {decision.item_id}")
        seen_item_ids.add(decision.item_id)
        source_path = (source_archive / decision.source_file).resolve()
        if source_path.parent != source_archive.resolve():
            raise DataUnavailableError("Verification decision source file escapes the source archive")
        try:
            source = json.loads(source_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as error:
            raise DataUnavailableError(f"Cannot read item source record {source_path}") from error
        item = promote_observation(observe_equipment(source), decision, available_source_ids)
        documents.append(asdict(item))
    documents.sort(key=lambda item: item["item_id"])
    return documents
