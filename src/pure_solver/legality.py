"""Equipment legality: ``EquipmentItem`` documents, ``Loadout`` slot assignments, ``LegalityContext`` (completed
quests, unverified-item policy), per-item and per-loadout legality checks, and legal loadout enumeration.

Ported to Rust as ``pure_math/src/items.rs``.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from itertools import product

from .accounts import AccountState
from .canonical import canonical_hash
from .errors import LegalityError

F2P_STANDARD_WORLD_SCOPE = "f2p_standard_world"
_ACCOUNT_REQUIREMENT_SKILLS = {
    "attack",
    "strength",
    "ranged",
    "magic",
    "prayer",
    "defence",
    "hitpoints",
}


@dataclass(frozen=True)
class EquipmentItem:
    item_id: int
    name: str
    free_to_play: bool
    members: bool
    obtainable: bool
    slot: str
    requirements: Mapping[str, int]
    bonuses: Mapping[str, int]
    quest_requirements: tuple[str, ...] = ()
    two_handed: bool = False
    weapon_type: str | None = None
    attack_speed: int | None = None
    attack_range: int | None = None
    attack_styles: tuple[str, ...] = ()
    ammo_ids: tuple[int, ...] = ()
    spell_ids: tuple[str, ...] = ()
    mechanic_flags: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    status: str = "unverified"
    availability_scope: str = "unverified"

    @classmethod
    def from_document(cls, raw: Mapping[str, object]) -> EquipmentItem:
        return cls.from_document_with_policy(raw, allow_unverified=False)

    @classmethod
    def from_document_with_policy(
        cls,
        raw: Mapping[str, object],
        *,
        allow_unverified: bool = False,
    ) -> EquipmentItem:
        required = {
            "item_id",
            "name",
            "free_to_play",
            "members",
            "obtainable",
            "slot",
            "requirements",
            "bonuses",
            "source_ids",
            "status",
            "availability_scope",
        }
        missing = required - set(raw)
        if missing:
            raise LegalityError(f"Equipment record is missing required fields: {sorted(missing)}")
        if isinstance(raw["item_id"], bool) or not isinstance(raw["item_id"], int) or raw["item_id"] <= 0:
            raise LegalityError("Equipment item_id must be a positive integer")
        for field in ("free_to_play", "members", "obtainable"):
            if not isinstance(raw[field], bool):
                raise LegalityError(f"Equipment field {field!r} must be a boolean")
        if not isinstance(raw["name"], str) or not raw["name"].strip():
            raise LegalityError("Equipment name must be a non-empty string")
        if not isinstance(raw["slot"], str) or not raw["slot"].strip():
            raise LegalityError("Equipment slot must be a non-empty string")
        if not isinstance(raw["requirements"], Mapping) or not isinstance(raw["bonuses"], Mapping):
            raise LegalityError("Equipment requirements and bonuses must be mappings")
        if not isinstance(raw["source_ids"], (list, tuple)) or not raw["source_ids"]:
            raise LegalityError("Equipment record needs at least one provenance source")
        if any(not isinstance(source_id, str) or not source_id.strip() for source_id in raw["source_ids"]):
            raise LegalityError("Equipment provenance sources must be non-empty strings")
        status = str(raw["status"])
        if status not in {"verified", "observed"} and not allow_unverified:
            raise LegalityError("Only verified equipment records may enter a ruleset")
        if status not in {"verified", "observed", "wiki_trusted"}:
            raise LegalityError(f"Equipment status {status!r} is unsupported")
        if raw["availability_scope"] != F2P_STANDARD_WORLD_SCOPE:
            raise LegalityError("Equipment record is outside the supported F2P standard-world scope")
        requirements = {str(key): int(value) for key, value in raw["requirements"].items()}
        if set(requirements) - _ACCOUNT_REQUIREMENT_SKILLS or any(value < 0 for value in requirements.values()):
            raise LegalityError("Equipment requirements contain unsupported or negative levels")
        return cls(
            item_id=raw["item_id"],
            name=raw["name"].strip(),
            free_to_play=raw["free_to_play"],
            members=raw["members"],
            obtainable=raw["obtainable"],
            slot=raw["slot"].strip(),
            requirements=requirements,
            quest_requirements=tuple(sorted(map(str, raw.get("quest_requirements", [])))),
            bonuses={str(key): int(value) for key, value in dict(raw["bonuses"]).items()},
            two_handed=bool(raw.get("two_handed", False)),
            weapon_type=raw.get("weapon_type") and str(raw["weapon_type"]),
            attack_speed=raw.get("attack_speed") and int(raw["attack_speed"]),
            attack_range=raw.get("attack_range") and int(raw["attack_range"]),
            attack_styles=tuple(map(str, raw.get("attack_styles", []))),
            ammo_ids=tuple(map(int, raw.get("ammo_ids", []))),
            spell_ids=tuple(map(str, raw.get("spell_ids", []))),
            mechanic_flags=tuple(sorted(map(str, raw.get("mechanic_flags", [])))),
            source_ids=tuple(map(str, raw["source_ids"])),
            status=status,
            availability_scope=str(raw["availability_scope"]),
        )


@dataclass(frozen=True)
class Loadout:
    items: tuple[EquipmentItem, ...]

    @property
    def canonical_id(self) -> str:
        return canonical_hash(sorted(item.item_id for item in self.items))

    def item_in_slot(self, slot: str) -> EquipmentItem | None:
        return next((item for item in self.items if item.slot == slot), None)


@dataclass(frozen=True)
class LegalityContext:
    completed_quests: frozenset[str] = frozenset()
    allow_unverified_items: bool = False


def is_item_legal(
    item: EquipmentItem,
    account: AccountState,
    context: LegalityContext = LegalityContext(),
) -> bool:
    if item.status == "verified" or (context.allow_unverified_items and item.status in {"observed", "wiki_trusted"}):
        pass
    else:
        return False
    if item.availability_scope != F2P_STANDARD_WORLD_SCOPE or not item.source_ids:
        return False
    if not item.free_to_play or item.members or not item.obtainable:
        return False
    level_by_requirement = {
        "attack": account.attack_level,
        "strength": account.strength_level,
        "ranged": account.ranged_level,
        "magic": account.magic_level,
        "prayer": account.prayer_level,
        "defence": account.defence_level,
        "hitpoints": account.hitpoints_level,
    }
    return all(
        level_by_requirement.get(skill, -1) >= required for skill, required in item.requirements.items()
    ) and set(item.quest_requirements).issubset(context.completed_quests)


def is_loadout_legal(
    loadout: Loadout,
    account: AccountState,
    context: LegalityContext = LegalityContext(),
) -> bool:
    if not all(is_item_legal(item, account, context) for item in loadout.items):
        return False
    slots = [item.slot for item in loadout.items]
    if len(set(slots)) != len(slots):
        return False
    one_handed_weapon = loadout.item_in_slot("weapon")
    two_handed_weapon = loadout.item_in_slot("2h")
    if one_handed_weapon and two_handed_weapon:
        return False
    weapon = one_handed_weapon or two_handed_weapon
    shield = loadout.item_in_slot("shield")
    if weapon and weapon.two_handed and shield:
        return False
    ammunition = loadout.item_in_slot("ammo")
    if ammunition and (weapon is None or ammunition.item_id not in weapon.ammo_ids):
        return False
    return True


def legal_loadouts(
    account: AccountState,
    items: Iterable[EquipmentItem],
    slots: tuple[str, ...],
    *,
    prune_dominated: bool = True,
    context: LegalityContext = LegalityContext(),
) -> Iterator[Loadout]:
    """Generate only legal equipment combinations before any combat evaluation."""
    item_list = list(items)
    if prune_dominated:
        # Local import breaks the import cycle with dominance.py, which imports is_item_legal from this module.
        from .dominance import prune_dominated_items

        item_list = list(prune_dominated_items(account, item_list, context=context).retained)
    by_slot: dict[str, list[EquipmentItem | None]] = {slot: [None] for slot in slots}
    for item in item_list:
        if item.slot in by_slot and is_item_legal(item, account, context):
            by_slot[item.slot].append(item)
    for combination in product(*(by_slot[slot] for slot in slots)):
        loadout = Loadout(tuple(item for item in combination if item is not None))
        if is_loadout_legal(loadout, account, context):
            yield loadout
