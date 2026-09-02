"""Load a versioned ruleset directory (manifest, mechanics, items, consumables, source archive) into an immutable
``Ruleset`` with reproducibility metadata, production preflight, and source-archive verification.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from .canonical import canonical_hash
from .errors import DataUnavailableError, LegalityError
from .legality import F2P_STANDARD_WORLD_SCOPE, EquipmentItem
from .mechanics import MechanicRegistry


@dataclass(frozen=True)
class Ruleset:
    root: Path
    ruleset_id: str
    solver_version: str
    data_snapshot_id: str
    retrieval_timestamp: str
    mechanics: MechanicRegistry
    items: tuple[Mapping[str, Any], ...]
    consumables: tuple[Mapping[str, Any], ...]
    required_mechanics: tuple[str, ...]
    inventory_slots: int
    combat_level_minimum: int
    combat_level_maximum: int
    defence_level: int
    source_archive: Path | None = None

    @cached_property
    def item_database_hash(self) -> str:
        return canonical_hash(self.items)

    @cached_property
    def mechanics_database_hash(self) -> str:
        return self.mechanics.mechanics_hash

    @cached_property
    def consumable_database_hash(self) -> str:
        return canonical_hash(self.consumables)

    @property
    def reproducibility_metadata(self) -> Mapping[str, Any]:
        return {
            "ruleset_id": self.ruleset_id,
            "solver_version": self.solver_version,
            "data_snapshot_id": self.data_snapshot_id,
            "retrieval_timestamp": self.retrieval_timestamp,
            "inventory_slots": self.inventory_slots,
            "combat_level_minimum": self.combat_level_minimum,
            "combat_level_maximum": self.combat_level_maximum,
            "defence_level": self.defence_level,
            "source_revisions": {
                source_id: source.revision for source_id, source in self.mechanics.source_revisions.items()
            },
            "item_database_hash": self.item_database_hash,
            "consumable_database_hash": self.consumable_database_hash,
            "mechanics_database_hash": self.mechanics_database_hash,
        }

    def preflight(
        self, required_mechanics: tuple[str, ...] | list[str] | None = None, *, allow_unverified_items: bool = False
    ) -> None:
        self.verify_catalogs(allow_unverified_items=allow_unverified_items)
        self.verify_source_archive()
        self.mechanics.check_required(required_mechanics or self.required_mechanics)

    def verify_catalogs(self, *, allow_unverified_items: bool = False) -> None:
        """Reject data that is not verified for this ruleset's exact world scope."""
        known_sources = set(self.mechanics.source_revisions)
        item_ids: set[int] = set()
        for document in self.items:
            try:
                item = EquipmentItem.from_document_with_policy(document, allow_unverified=allow_unverified_items)
            except LegalityError as error:
                raise DataUnavailableError(f"Invalid equipment record in ruleset: {error}") from error
            if item.item_id in item_ids:
                raise DataUnavailableError(f"Ruleset contains duplicate equipment item ID {item.item_id}")
            item_ids.add(item.item_id)
            if not item.free_to_play or item.members or not item.obtainable:
                raise DataUnavailableError(f"Equipment item {item.name!r} is not obtainable F2P standard-world gear")
            unknown_sources = set(item.source_ids) - known_sources
            if unknown_sources:
                raise DataUnavailableError(
                    f"Equipment item {item.name!r} cites unavailable sources: {sorted(unknown_sources)}"
                )

        consumable_ids: set[str] = set()
        for document in self.consumables:
            if not isinstance(document, Mapping):
                raise DataUnavailableError("Ruleset consumable record is not an object")
            consumable_id = document.get("consumable_id")
            if not isinstance(consumable_id, str) or not consumable_id.strip():
                raise DataUnavailableError("Ruleset consumable has no non-empty consumable_id")
            if consumable_id in consumable_ids:
                raise DataUnavailableError(f"Ruleset contains duplicate consumable ID {consumable_id!r}")
            consumable_ids.add(consumable_id)
            if document.get("status") != "verified":
                raise DataUnavailableError(f"Consumable {consumable_id!r} is not verified")
            if document.get("availability_scope") != F2P_STANDARD_WORLD_SCOPE:
                raise DataUnavailableError(
                    f"Consumable {consumable_id!r} is outside the supported F2P standard-world scope"
                )
            source_ids = document.get("source_ids")
            if (
                not isinstance(source_ids, (list, tuple))
                or not source_ids
                or any(not isinstance(source_id, str) or not source_id.strip() for source_id in source_ids)
            ):
                raise DataUnavailableError(f"Consumable {consumable_id!r} has no valid provenance sources")
            unknown_sources = set(source_ids) - known_sources
            if unknown_sources:
                raise DataUnavailableError(
                    f"Consumable {consumable_id!r} cites unavailable sources: {sorted(unknown_sources)}"
                )
            if not isinstance(document.get("transitions"), Mapping) or not document["transitions"]:
                raise DataUnavailableError(f"Consumable {consumable_id!r} has no transition graph")

    def verify_source_archive(self) -> None:
        """Prove that pinned source records still match their raw archived pages."""
        sources_with_hashes = [source for source in self.mechanics.source_revisions.values() if source.content_sha256]
        if not sources_with_hashes:
            return
        if self.source_archive is None or not self.source_archive.is_dir():
            raise DataUnavailableError("Ruleset cites content hashes but has no readable source archive")
        archive_records: dict[tuple[str, str, str], Mapping[str, Any]] = {}
        for path in self.source_archive.glob("*.json"):
            raw = _read_json(path)
            if isinstance(raw, Mapping) and raw.get("url") and raw.get("revision") and raw.get("content_sha256"):
                archive_records[(str(raw["url"]), str(raw["revision"]), str(raw["content_sha256"]))] = raw
        for source in sources_with_hashes:
            key = (source.url, source.revision, source.content_sha256 or "")
            raw = archive_records.get(key)
            if raw is None:
                raise DataUnavailableError(
                    f"Source archive has no raw record for {source.source_id!r} at revision {source.revision}"
                )
            content = raw.get("content")
            if not isinstance(content, str):
                raise DataUnavailableError(f"Archived source {source.source_id!r} has no raw content")
            actual = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if actual != source.content_sha256:
                raise DataUnavailableError(
                    f"Archived source {source.source_id!r} checksum mismatch: "
                    f"expected {source.content_sha256}, got {actual}"
                )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise DataUnavailableError(f"Missing required ruleset file: {path}") from error
    except json.JSONDecodeError as error:
        raise DataUnavailableError(f"Invalid JSON in ruleset file {path}: {error}") from error


def load_ruleset(root: str | Path) -> Ruleset:
    root = Path(root).resolve()
    manifest = _read_json(root / "manifest.json")
    mechanics = MechanicRegistry.from_document(_read_json(root / "mechanics.json"))
    item_document = _read_json(root / "items.json")
    consumable_document = _read_json(root / "consumables.json")
    if not isinstance(item_document, list) or not isinstance(consumable_document, list):
        raise DataUnavailableError("Ruleset item and consumable snapshots must be JSON arrays")
    items = tuple(item_document)
    consumables = tuple(consumable_document)
    required_fields = ("ruleset_id", "solver_version", "data_snapshot_id", "retrieval_timestamp")
    missing = [field for field in required_fields if not manifest.get(field)]
    if missing:
        raise DataUnavailableError(f"Ruleset manifest is missing required fields: {', '.join(missing)}")
    environment = manifest.get("environment", {})
    inventory_slots = environment.get("inventory_slots")
    if not isinstance(inventory_slots, int) or inventory_slots <= 0:
        raise DataUnavailableError("Ruleset environment needs a positive integer inventory_slots")
    combat_level_minimum = environment.get("combat_level_minimum")
    combat_level_maximum = environment.get("combat_level_maximum")
    defence_level = environment.get("defence_level")
    if (
        not isinstance(combat_level_minimum, int)
        or not isinstance(combat_level_maximum, int)
        or combat_level_minimum < 1
        or combat_level_maximum < combat_level_minimum
    ):
        raise DataUnavailableError("Ruleset environment has invalid combat-level bounds")
    if defence_level != 1:
        raise DataUnavailableError("This solver ruleset requires exactly 1 Defence")
    ruleset = Ruleset(
        root=root,
        ruleset_id=manifest["ruleset_id"],
        solver_version=manifest["solver_version"],
        data_snapshot_id=manifest["data_snapshot_id"],
        retrieval_timestamp=manifest["retrieval_timestamp"],
        mechanics=mechanics,
        items=items,
        consumables=consumables,
        required_mechanics=tuple(manifest.get("required_mechanics", [])),
        inventory_slots=inventory_slots,
        combat_level_minimum=combat_level_minimum,
        combat_level_maximum=combat_level_maximum,
        defence_level=defence_level,
        source_archive=(root / manifest["source_archive"]).resolve() if manifest.get("source_archive") else None,
    )
    ruleset.verify_catalogs()
    return ruleset
