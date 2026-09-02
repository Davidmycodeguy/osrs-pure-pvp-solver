"""Canonical JSON serialisation (sorted keys, dataclasses via ``asdict``, ``Fraction`` as numerator/denominator)
and its SHA-256 digest, used for stable identifiers and provenance hashes.

Ported to Rust as ``pure_math/src/canonical.rs``; this module is the golden reference.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from fractions import Fraction
from typing import Any


def canonical_json(value: Any) -> str:
    """Produce a stable JSON representation suitable for IDs and provenance hashes."""

    def normalise(part: Any) -> Any:
        if is_dataclass(part):
            return normalise(asdict(part))
        if isinstance(part, Fraction):
            return {"numerator": part.numerator, "denominator": part.denominator}
        if isinstance(part, dict):
            return {str(key): normalise(value) for key, value in sorted(part.items())}
        if isinstance(part, (tuple, list)):
            return [normalise(value) for value in part]
        if isinstance(part, set):
            return [normalise(value) for value in sorted(part, key=repr)]
        return part

    return json.dumps(normalise(value), separators=(",", ":"), sort_keys=True, ensure_ascii=True)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
