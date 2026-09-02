"""Equipment catalog built from a Wiki observation snapshot plus the verified item table: duplicate and lineage
grouping, a validation queue, a promotion queue, a completeness summary and account-relevant subsets.
LMS/Deadman-scoped observations are kept audit-only.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .accounts import AccountState
from .canonical import canonical_hash
from .errors import DataUnavailableError
from .legality import EquipmentItem, is_item_legal
from .wiki_items import WikiItemObservation

_PAREN_SUFFIX = re.compile(r"\s+\([^)]*\)$")
_OUT_OF_SCOPE_MARKERS = ("last man standing", "deadman")
_SLOT_ORDER = {
    "weapon": 0,
    "2h": 1,
    "ammo": 2,
    "shield": 3,
    "head": 4,
    "body": 5,
    "legs": 6,
    "hands": 7,
    "feet": 8,
    "cape": 9,
    "neck": 10,
    "ring": 11,
}
_OFFENSIVE_KEYS = (
    "attack_stab",
    "attack_slash",
    "attack_crush",
    "attack_magic",
    "attack_ranged",
    "melee_strength",
    "ranged_strength",
    "magic_damage",
)
_DEFENSIVE_KEYS = (
    "defence_stab",
    "defence_slash",
    "defence_crush",
    "defence_magic",
    "defence_ranged",
    "prayer",
)


def _sorted_requirements(requirements: Mapping[str, int]) -> dict[str, int]:
    return {str(skill): int(level) for skill, level in sorted(requirements.items())}


def _lineage_name(name: str) -> str:
    return _PAREN_SUFFIX.sub("", name).casefold().strip()


def _slot_rank(slot: str) -> int:
    return _SLOT_ORDER.get(slot, len(_SLOT_ORDER))


def _combat_role(slot: str, bonuses: Mapping[str, int]) -> str:
    if slot in {"weapon", "2h", "ammo"} or any(bonuses.get(key, 0) != 0 for key in _OFFENSIVE_KEYS):
        return "offensive"
    if any(bonuses.get(key, 0) != 0 for key in _DEFENSIVE_KEYS):
        return "defensive"
    return "utility"


def _role_rank(role: str) -> int:
    return {"offensive": 0, "defensive": 1, "utility": 2}.get(role, 3)


def _requirements_met(requirements: Mapping[str, int], account: AccountState) -> bool:
    levels = {
        "attack": account.attack_level,
        "strength": account.strength_level,
        "ranged": account.ranged_level,
        "magic": account.magic_level,
        "prayer": account.prayer_level,
        "defence": account.defence_level,
        "hitpoints": account.hitpoints_level,
    }
    return all(levels.get(skill, -1) >= level for skill, level in requirements.items())


def _source_is_environment_scoped(title: str) -> bool:
    lowered = title.casefold()
    return any(marker in lowered for marker in _OUT_OF_SCOPE_MARKERS)


def _is_environment_scoped(item: ObservedCatalogItem) -> bool:
    return item.observation.environment_scope is not None or _source_is_environment_scoped(item.source_title)


@dataclass(frozen=True)
class ObservedCatalogItem:
    snapshot_index: int
    source_title: str
    source_revision: str
    source_id: str
    source_url: str | None
    observation: WikiItemObservation

    @classmethod
    def from_snapshot_entry(cls, raw: Mapping[str, Any], index: int) -> ObservedCatalogItem:
        source = raw.get("source")
        observation = raw.get("observation")
        if not isinstance(source, Mapping) or not isinstance(observation, Mapping):
            raise DataUnavailableError("Observation snapshot entry is missing source or observation data")
        return cls(
            snapshot_index=index,
            source_title=str(source["title"]),
            source_revision=str(source["revision"]),
            source_id=str(source["source_id"]),
            source_url=source.get("url") and str(source["url"]),
            observation=WikiItemObservation(
                item_id=int(observation["item_id"]),
                name=str(observation["name"]),
                free_to_play=bool(observation["free_to_play"]),
                members=bool(observation["members"]),
                equipable=bool(observation["equipable"]),
                slot=str(observation["slot"]),
                requirements=_sorted_requirements(observation.get("requirements", {})),
                bonuses={str(key): int(value) for key, value in dict(observation.get("bonuses", {})).items()},
                attack_speed=observation.get("attack_speed")
                if observation.get("attack_speed") is None
                else int(observation["attack_speed"]),
                attack_range=observation.get("attack_range")
                if observation.get("attack_range") is None
                else int(observation["attack_range"]),
                combat_style=observation.get("combat_style") and str(observation["combat_style"]),
                source_ids=tuple(map(str, observation.get("source_ids", ()))),
                status=str(observation["status"]),
                verification_gaps=tuple(map(str, observation.get("verification_gaps", ()))),
                environment_scope=observation.get("environment_scope") and str(observation["environment_scope"]),
            ),
        )

    @property
    def item_id(self) -> int:
        return self.observation.item_id

    @property
    def name(self) -> str:
        return self.observation.name

    @property
    def slot(self) -> str:
        return self.observation.slot

    @property
    def requirements(self) -> Mapping[str, int]:
        return self.observation.requirements

    @property
    def lineage_key(self) -> tuple[str, str]:
        return self.slot, _lineage_name(self.name)

    @property
    def exact_name_slot_key(self) -> tuple[str, str]:
        return self.slot, self.name.casefold()

    @property
    def combat_role(self) -> str:
        return _combat_role(self.slot, self.observation.bonuses)

    @property
    def requirement_score(self) -> tuple[int, int, int, int, int, int, int]:
        requirements = self.requirements
        return (
            requirements.get("attack", 0),
            requirements.get("strength", 0),
            requirements.get("ranged", 0),
            requirements.get("magic", 0),
            requirements.get("prayer", 0),
            requirements.get("defence", 0),
            requirements.get("hitpoints", 0),
        )

    @property
    def group_signature(self) -> str:
        return canonical_hash(
            {
                "slot": self.slot,
                "requirements": _sorted_requirements(self.requirements),
                "bonuses": _sorted_requirements(self.observation.bonuses),
                "attack_speed": self.observation.attack_speed,
                "attack_range": self.observation.attack_range,
                "combat_style": self.observation.combat_style,
                "free_to_play": self.observation.free_to_play,
                "members": self.observation.members,
                "equipable": self.observation.equipable,
            }
        )

    @property
    def coverage_signature(self) -> str:
        return canonical_hash(
            {
                "slot": self.slot,
                "requirements": _sorted_requirements(self.requirements),
                "bonuses": _sorted_requirements(self.observation.bonuses),
                "attack_speed": self.observation.attack_speed,
                "attack_range": self.observation.attack_range,
                "free_to_play": self.observation.free_to_play,
                "members": self.observation.members,
                "equipable": self.observation.equipable,
            }
        )


@dataclass(frozen=True)
class CatalogFailure:
    title: str
    revision: str
    error: str

    @classmethod
    def from_document(cls, raw: Mapping[str, Any]) -> CatalogFailure:
        return cls(title=str(raw["title"]), revision=str(raw["revision"]), error=str(raw["error"]))


@dataclass(frozen=True)
class CatalogDuplicateGroup:
    kind: str
    key: str
    slot: str
    item_ids: tuple[int, ...]
    names: tuple[str, ...]
    source_titles: tuple[str, ...]
    signature_count: int


@dataclass(frozen=True)
class CatalogValidationIssue:
    code: str
    severity: str
    summary: str
    item_ids: tuple[int, ...] = ()
    names: tuple[str, ...] = ()
    source_titles: tuple[str, ...] = ()
    details: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PromotionCandidate:
    signature: str
    representative_item_id: int
    representative_name: str
    slot: str
    combat_role: str
    requirements: Mapping[str, int]
    attack_speed: int | None
    attack_range: int | None
    member_item_ids: tuple[int, ...]
    member_names: tuple[str, ...]
    member_titles: tuple[str, ...]
    account_legal_by_observation: bool
    covered_by_verified_item_ids: tuple[int, ...]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class SlotCompleteness:
    observed: int
    pending: int
    promotion_groups: int
    verified: int


@dataclass(frozen=True)
class CatalogSummary:
    observation_count: int
    failure_count: int
    verified_item_count: int
    pending_item_count: int
    promotion_group_count: int
    duplicate_name_slot_group_count: int
    lineage_group_count: int
    lineage_conflict_count: int
    covered_pending_group_count: int
    by_slot: Mapping[str, SlotCompleteness]


@dataclass(frozen=True)
class AccountRelevantSubset:
    account_id: str
    legal_verified_item_ids: tuple[int, ...]
    legal_verified_names: tuple[str, ...]
    pending_groups: tuple[PromotionCandidate, ...]
    blocked_group_count: int
    covered_group_count: int
    uncovered_group_count: int


class EquipmentCatalog:
    def __init__(
        self,
        observations: Sequence[ObservedCatalogItem],
        failures: Sequence[CatalogFailure],
        verified_items: Sequence[EquipmentItem] = (),
        *,
        observation_snapshot_id: str | None = None,
        query: str | None = None,
    ) -> None:
        self.observations = tuple(observations)
        self.failures = tuple(failures)
        self.verified_items = tuple(verified_items)
        self.observation_snapshot_id = observation_snapshot_id
        self.query = query
        self._verified_by_item_id = {item.item_id: item for item in self.verified_items}
        self._verified_comparable_signatures = defaultdict(list)
        for item in self.verified_items:
            self._verified_comparable_signatures[self._verified_signature(item)].append(item.item_id)

    @classmethod
    def from_documents(
        cls,
        snapshot: Mapping[str, Any],
        *,
        verified_items: Iterable[EquipmentItem] = (),
    ) -> EquipmentCatalog:
        observations = [
            ObservedCatalogItem.from_snapshot_entry(raw, index)
            for index, raw in enumerate(snapshot.get("observations", ()))
        ]
        failures = [CatalogFailure.from_document(raw) for raw in snapshot.get("failures", ())]
        return cls(
            observations,
            failures,
            list(verified_items),
            observation_snapshot_id=snapshot.get("observation_snapshot_id")
            and str(snapshot["observation_snapshot_id"]),
            query=snapshot.get("query") and str(snapshot["query"]),
        )

    @classmethod
    def from_paths(
        cls,
        snapshot_path: str | Path,
        *,
        verified_items_path: str | Path | None = None,
    ) -> EquipmentCatalog:
        snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        verified_items: list[EquipmentItem] = []
        if verified_items_path is not None:
            verified_items = [
                EquipmentItem.from_document(item)
                for item in json.loads(Path(verified_items_path).read_text(encoding="utf-8"))
            ]
        return cls.from_documents(snapshot, verified_items=verified_items)

    @staticmethod
    def _verified_signature(item: EquipmentItem) -> str:
        return canonical_hash(
            {
                "slot": item.slot,
                "requirements": _sorted_requirements(item.requirements),
                "bonuses": _sorted_requirements(item.bonuses),
                "attack_speed": item.attack_speed,
                "attack_range": item.attack_range,
                "free_to_play": item.free_to_play,
                "members": item.members,
                "equipable": True,
            }
        )

    def _groups_by_signature(self) -> dict[str, list[ObservedCatalogItem]]:
        groups: dict[str, list[ObservedCatalogItem]] = defaultdict(list)
        for entry in self.observations:
            groups[entry.group_signature].append(entry)
        for items in groups.values():
            items.sort(key=lambda entry: (entry.snapshot_index, entry.item_id))
        return dict(groups)

    def _groups_by_lineage(self) -> dict[tuple[str, str], list[ObservedCatalogItem]]:
        groups: dict[tuple[str, str], list[ObservedCatalogItem]] = defaultdict(list)
        for entry in self.observations:
            groups[entry.lineage_key].append(entry)
        for items in groups.values():
            items.sort(key=lambda entry: (entry.name.casefold(), entry.item_id))
        return dict(groups)

    def _groups_by_name_slot(self) -> dict[tuple[str, str], list[ObservedCatalogItem]]:
        groups: dict[tuple[str, str], list[ObservedCatalogItem]] = defaultdict(list)
        for entry in self.observations:
            groups[entry.exact_name_slot_key].append(entry)
        for items in groups.values():
            items.sort(key=lambda entry: entry.item_id)
        return dict(groups)

    def duplicate_groups(self) -> tuple[CatalogDuplicateGroup, ...]:
        groups: list[CatalogDuplicateGroup] = []
        for (slot, name), items in self._groups_by_name_slot().items():
            if len(items) < 2:
                continue
            groups.append(
                CatalogDuplicateGroup(
                    kind="duplicate_name_slot",
                    key=f"{slot}:{name}",
                    slot=slot,
                    item_ids=tuple(item.item_id for item in items),
                    names=tuple(item.name for item in items),
                    source_titles=tuple(item.source_title for item in items),
                    signature_count=len({item.group_signature for item in items}),
                )
            )
        for (slot, lineage), items in self._groups_by_lineage().items():
            if len(items) < 2:
                continue
            groups.append(
                CatalogDuplicateGroup(
                    kind="lineage",
                    key=f"{slot}:{lineage}",
                    slot=slot,
                    item_ids=tuple(item.item_id for item in items),
                    names=tuple(item.name for item in items),
                    source_titles=tuple(item.source_title for item in items),
                    signature_count=len({item.group_signature for item in items}),
                )
            )
        for signature, items in self._groups_by_signature().items():
            if len(items) < 2:
                continue
            groups.append(
                CatalogDuplicateGroup(
                    kind="exact_signature",
                    key=signature,
                    slot=items[0].slot,
                    item_ids=tuple(item.item_id for item in items),
                    names=tuple(item.name for item in items),
                    source_titles=tuple(item.source_title for item in items),
                    signature_count=1,
                )
            )
        groups.sort(
            key=lambda group: (group.kind, _slot_rank(group.slot), group.names[0].casefold(), group.item_ids[0])
        )
        return tuple(groups)

    def validation_queue(self) -> tuple[CatalogValidationIssue, ...]:
        issues: list[CatalogValidationIssue] = []
        for failure in sorted(self.failures, key=lambda item: (item.title.casefold(), item.revision, item.error)):
            issues.append(
                CatalogValidationIssue(
                    code="parser_failure",
                    severity="error",
                    summary=f"{failure.title} ({failure.revision}) did not parse cleanly",
                    source_titles=(failure.title,),
                    details={"revision": failure.revision, "error": failure.error},
                )
            )
        observed_ids = {entry.item_id for entry in self.observations}
        for item in sorted(self.verified_items, key=lambda value: value.item_id):
            if item.item_id not in observed_ids:
                issues.append(
                    CatalogValidationIssue(
                        code="verified_item_missing_from_snapshot",
                        severity="error",
                        summary=f"Verified item {item.name} ({item.item_id}) is absent from the observation snapshot",
                        item_ids=(item.item_id,),
                        names=(item.name,),
                    )
                )
        for (slot, lineage), items in self._groups_by_lineage().items():
            signatures = {item.group_signature for item in items}
            if len(items) < 2 or len(signatures) == 1:
                continue
            issues.append(
                CatalogValidationIssue(
                    code="lineage_conflict",
                    severity="warning",
                    summary=f"{slot} lineage {lineage!r} has {len(signatures)} distinct observed signatures",
                    item_ids=tuple(item.item_id for item in items),
                    names=tuple(item.name for item in items),
                    source_titles=tuple(item.source_title for item in items),
                    details={"signature_count": len(signatures)},
                )
            )
        for signature, items in self._groups_by_signature().items():
            if items and all(_is_environment_scoped(item) for item in items):
                issues.append(
                    CatalogValidationIssue(
                        code="environment_scoped_variant",
                        severity="warning",
                        summary=(
                            f"Observed group {items[0].name!r} is restricted to LMS/Deadman context "
                            "and is blocked from the normal F2P 1v1 promotion queue"
                        ),
                        item_ids=tuple(item.item_id for item in items),
                        names=tuple(item.name for item in items),
                        source_titles=tuple(item.source_title for item in items),
                        details={"signature": signature},
                    )
                )
        issues.sort(
            key=lambda issue: (
                0 if issue.severity == "error" else 1,
                issue.code,
                issue.summary.casefold(),
                issue.item_ids[:1] or (0,),
            )
        )
        return tuple(issues)

    def promotion_queue(self, account: AccountState | None = None) -> tuple[PromotionCandidate, ...]:
        pending_groups: list[PromotionCandidate] = []
        # LMS/Deadman observations remain in validation_queue for auditability,
        # but are never candidates for promotion into the standard F2P ruleset.
        promotable = tuple(item for item in self.observations if not _is_environment_scoped(item))
        groups_by_signature: dict[str, list[ObservedCatalogItem]] = defaultdict(list)
        groups_by_lineage: dict[tuple[str, str], list[ObservedCatalogItem]] = defaultdict(list)
        for item in promotable:
            groups_by_signature[item.group_signature].append(item)
            groups_by_lineage[item.lineage_key].append(item)
        lineage_sizes = {key: len(items) for key, items in groups_by_lineage.items()}
        for signature, items in groups_by_signature.items():
            if any(item.item_id in self._verified_by_item_id for item in items):
                continue
            representative = min(
                items,
                key=lambda item: (
                    _slot_rank(item.slot),
                    item.requirement_score,
                    item.name.casefold(),
                    item.item_id,
                ),
            )
            account_legal = account is None or (
                representative.observation.free_to_play
                and representative.observation.equipable
                and not representative.observation.members
                and _requirements_met(representative.requirements, account)
            )
            covered_by_verified = tuple(
                sorted(self._verified_comparable_signatures.get(representative.coverage_signature, ()))
            )
            tags = [
                f"role:{representative.combat_role}",
                "account_legal_by_observation" if account_legal else "account_blocked_by_observed_requirements",
            ]
            if len(items) > 1:
                tags.append(f"collapsed_equivalents:{len(items)}")
            lineage_group_size = lineage_sizes.get(representative.lineage_key, 1)
            if lineage_group_size > 1:
                tags.append(f"lineage_group:{lineage_group_size}")
            if covered_by_verified:
                tags.append("covered_by_verified_signature")
            pending_groups.append(
                PromotionCandidate(
                    signature=signature,
                    representative_item_id=representative.item_id,
                    representative_name=representative.name,
                    slot=representative.slot,
                    combat_role=representative.combat_role,
                    requirements=_sorted_requirements(representative.requirements),
                    attack_speed=representative.observation.attack_speed,
                    attack_range=representative.observation.attack_range,
                    member_item_ids=tuple(item.item_id for item in items),
                    member_names=tuple(item.name for item in items),
                    member_titles=tuple(item.source_title for item in items),
                    account_legal_by_observation=account_legal,
                    covered_by_verified_item_ids=covered_by_verified,
                    tags=tuple(tags),
                )
            )
        pending_groups.sort(
            key=lambda candidate: (
                0 if candidate.account_legal_by_observation else 1,
                _role_rank(candidate.combat_role),
                1 if candidate.covered_by_verified_item_ids else 0,
                _slot_rank(candidate.slot),
                tuple(
                    candidate.requirements.get(skill, 0)
                    for skill in ("attack", "strength", "ranged", "magic", "prayer", "defence", "hitpoints")
                ),
                candidate.representative_name.casefold(),
                candidate.representative_item_id,
            )
        )
        return tuple(pending_groups)

    def summary(self) -> CatalogSummary:
        pending_item_ids = {
            entry.item_id for entry in self.observations if entry.item_id not in self._verified_by_item_id
        }
        pending_groups = self.promotion_queue()
        duplicates = self.duplicate_groups()
        lineage_conflicts = [issue for issue in self.validation_queue() if issue.code == "lineage_conflict"]
        observed_by_slot = Counter(entry.slot for entry in self.observations)
        pending_by_slot = Counter(entry.slot for entry in self.observations if entry.item_id in pending_item_ids)
        verified_by_slot = Counter(item.slot for item in self.verified_items)
        groups_by_slot = Counter(candidate.slot for candidate in pending_groups)
        by_slot = {
            slot: SlotCompleteness(
                observed=observed_by_slot.get(slot, 0),
                pending=pending_by_slot.get(slot, 0),
                promotion_groups=groups_by_slot.get(slot, 0),
                verified=verified_by_slot.get(slot, 0),
            )
            for slot in sorted(set(observed_by_slot) | set(pending_by_slot) | set(verified_by_slot), key=_slot_rank)
        }
        return CatalogSummary(
            observation_count=len(self.observations),
            failure_count=len(self.failures),
            verified_item_count=len(self.verified_items),
            pending_item_count=len(pending_item_ids),
            promotion_group_count=len(pending_groups),
            duplicate_name_slot_group_count=sum(1 for group in duplicates if group.kind == "duplicate_name_slot"),
            lineage_group_count=sum(1 for group in duplicates if group.kind == "lineage"),
            lineage_conflict_count=len(lineage_conflicts),
            covered_pending_group_count=sum(1 for group in pending_groups if group.covered_by_verified_item_ids),
            by_slot=by_slot,
        )

    def relevant_subset(self, account: AccountState) -> AccountRelevantSubset:
        legal_verified = sorted(
            (item for item in self.verified_items if is_item_legal(item, account)),
            key=lambda item: (_slot_rank(item.slot), item.name.casefold(), item.item_id),
        )
        pending_groups = self.promotion_queue(account)
        legal_pending = tuple(group for group in pending_groups if group.account_legal_by_observation)
        covered = sum(1 for group in legal_pending if group.covered_by_verified_item_ids)
        return AccountRelevantSubset(
            account_id=account.canonical_id,
            legal_verified_item_ids=tuple(item.item_id for item in legal_verified),
            legal_verified_names=tuple(item.name for item in legal_verified),
            pending_groups=legal_pending,
            blocked_group_count=len(pending_groups) - len(legal_pending),
            covered_group_count=covered,
            uncovered_group_count=len(legal_pending) - covered,
        )
