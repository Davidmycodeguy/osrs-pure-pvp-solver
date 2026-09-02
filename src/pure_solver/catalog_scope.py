"""Audit of a catalog-scope document: normalise the candidate status groups (promoted, dominance-pruned,
mechanics-blocked, environment-excluded, pending) and decide whether an exhaustive-search claim is safe.

Verified mechanic primitive that is not yet wired into the ranking pipeline; it is exercised by the test
suite.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import DataUnavailableError

_STATUS_ALIASES = {
    "promoted": "promoted",
    "optimized_candidates": "promoted",
    "dominance_pruned": "dominance_pruned",
    "verified_but_dominance_pruned": "dominance_pruned",
    "mechanics_blocked": "mechanics_blocked",
    "observed_but_blocked": "mechanics_blocked",
    "environment_excluded": "environment_excluded",
    "excluded": "environment_excluded",
    "pending": "pending",
    "observed_pending_promotion_or_dominance_proof": "pending",
}
_STATUS_ORDER = (
    "promoted",
    "dominance_pruned",
    "mechanics_blocked",
    "environment_excluded",
    "pending",
)


def _load_document(document_or_path: Mapping[str, Any] | str | Path) -> Mapping[str, Any]:
    if isinstance(document_or_path, Mapping):
        return document_or_path
    return json.loads(Path(document_or_path).read_text(encoding="utf-8"))


def _candidate_id(raw: Any) -> str:
    if isinstance(raw, (str, int)):
        return str(raw)
    if not isinstance(raw, Mapping):
        raise DataUnavailableError("Catalog scope candidates must be ids or mapping entries")
    if "id" in raw and isinstance(raw["id"], (str, int)):
        return str(raw["id"])
    id_keys = sorted(key for key, value in raw.items() if key.endswith("_id") and isinstance(value, (str, int)))
    if len(id_keys) == 1:
        return str(raw[id_keys[0]])
    if not id_keys:
        raise DataUnavailableError(f"Catalog scope entry is missing an id field: {raw!r}")
    raise DataUnavailableError(f"Catalog scope entry has ambiguous id fields {id_keys!r}: {raw!r}")


def _normalize_status_groups(document: Mapping[str, Any]) -> dict[str, tuple[Mapping[str, Any] | str, ...]]:
    groups: dict[str, list[Mapping[str, Any] | str]] = {status: [] for status in _STATUS_ORDER}
    for raw_key, normalized in _STATUS_ALIASES.items():
        raw_group = document.get(raw_key, ())
        if raw_group in (None, ()):
            continue
        if not isinstance(raw_group, Sequence) or isinstance(raw_group, (str, bytes, bytearray)):
            raise DataUnavailableError(f"Catalog scope field {raw_key!r} must be a sequence")
        groups[normalized].extend(raw_group)
    return {status: tuple(entries) for status, entries in groups.items()}


def _declared_candidates(document: Mapping[str, Any]) -> tuple[str, ...] | None:
    raw_candidates = document.get("candidate_ids")
    if raw_candidates is not None:
        if not isinstance(raw_candidates, Sequence) or isinstance(raw_candidates, (str, bytes, bytearray)):
            raise DataUnavailableError("Catalog scope field 'candidate_ids' must be a sequence")
        return tuple(_candidate_id(entry) for entry in raw_candidates)
    raw_catalog = document.get("candidates")
    if raw_catalog is None:
        return None
    if not isinstance(raw_catalog, Sequence) or isinstance(raw_catalog, (str, bytes, bytearray)):
        raise DataUnavailableError("Catalog scope field 'candidates' must be a sequence")
    return tuple(_candidate_id(entry) for entry in raw_catalog)


@dataclass(frozen=True)
class CatalogScopeAudit:
    scope: str
    candidate_ids: tuple[str, ...]
    promoted: tuple[str, ...]
    dominance_pruned: tuple[str, ...]
    mechanics_blocked: tuple[str, ...]
    environment_excluded: tuple[str, ...]
    pending: tuple[str, ...]
    declared_catalog_complete: bool
    production_catalog_complete: bool
    exhaustive_claim_safe: bool

    @property
    def counts(self) -> Mapping[str, int]:
        return {
            "candidate_count": len(self.candidate_ids),
            "promoted": len(self.promoted),
            "dominance_pruned": len(self.dominance_pruned),
            "mechanics_blocked": len(self.mechanics_blocked),
            "environment_excluded": len(self.environment_excluded),
            "pending": len(self.pending),
        }


def audit_catalog_scope(document_or_path: Mapping[str, Any] | str | Path) -> CatalogScopeAudit:
    document = _load_document(document_or_path)
    scope = document.get("scope")
    if not isinstance(scope, str) or not scope.strip():
        raise DataUnavailableError("Catalog scope document is missing a non-empty 'scope' field")

    normalized_groups = _normalize_status_groups(document)
    declared_candidates = _declared_candidates(document)
    status_by_id: dict[str, str] = {}
    ids_by_status: dict[str, list[str]] = {status: [] for status in _STATUS_ORDER}

    for status in _STATUS_ORDER:
        for entry in normalized_groups[status]:
            candidate_id = _candidate_id(entry)
            previous = status_by_id.get(candidate_id)
            if previous is not None:
                raise DataUnavailableError(
                    f"Catalog scope candidate {candidate_id!r} is classified more than once: "
                    f"{previous!r} and {status!r}"
                )
            status_by_id[candidate_id] = status
            ids_by_status[status].append(candidate_id)

    if declared_candidates is None:
        candidate_ids = tuple(sorted(status_by_id))
    else:
        duplicate_declared = sorted(
            {candidate_id for candidate_id in declared_candidates if declared_candidates.count(candidate_id) > 1}
        )
        if duplicate_declared:
            raise DataUnavailableError(f"Catalog scope declares duplicate candidates {duplicate_declared!r}")
        candidate_ids = tuple(declared_candidates)
        missing = [candidate_id for candidate_id in candidate_ids if candidate_id not in status_by_id]
        if missing:
            raise DataUnavailableError(f"Catalog scope candidates are missing a status classification: {missing!r}")
        unexpected = sorted(candidate_id for candidate_id in status_by_id if candidate_id not in set(candidate_ids))
        if unexpected:
            raise DataUnavailableError(f"Catalog scope classified undeclared candidates: {unexpected!r}")

    declared_catalog_complete = bool(document.get("catalog_complete", False))
    production_catalog_complete = not ids_by_status["pending"] and not ids_by_status["mechanics_blocked"]
    exhaustive_claim_safe = production_catalog_complete

    if declared_catalog_complete and not production_catalog_complete:
        if ids_by_status["pending"]:
            raise DataUnavailableError("Catalog scope cannot be marked complete while pending candidates remain")
        raise DataUnavailableError(
            "Catalog scope cannot be marked complete while mechanics-blocked candidates prevent an exhaustive claim"
        )

    return CatalogScopeAudit(
        scope=scope,
        candidate_ids=candidate_ids,
        promoted=tuple(ids_by_status["promoted"]),
        dominance_pruned=tuple(ids_by_status["dominance_pruned"]),
        mechanics_blocked=tuple(ids_by_status["mechanics_blocked"]),
        environment_excluded=tuple(ids_by_status["environment_excluded"]),
        pending=tuple(ids_by_status["pending"]),
        declared_catalog_complete=declared_catalog_complete,
        production_catalog_complete=production_catalog_complete,
        exhaustive_claim_safe=exhaustive_claim_safe,
    )


def load_catalog_scope(document_or_path: Mapping[str, Any] | str | Path) -> CatalogScopeAudit:
    return audit_catalog_scope(document_or_path)
