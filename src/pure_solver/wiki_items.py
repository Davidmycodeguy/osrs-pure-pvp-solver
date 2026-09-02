"""Parse pinned Wiki equipment pages: infobox template extraction, integer and yes/no fields, skill requirements
from the lead prose, and ``observe_equipment``, which yields an unpromoted ``WikiItemObservation``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from .errors import DataUnavailableError

_INTEGER = re.compile(r"^[+]?(-?\d[\d,]*)$")
_SKILLS = "Attack|Strength|Ranged|Magic|Prayer|Defence|Hitpoints"
_OUT_OF_SCOPE_MARKERS = ("last man standing", "deadman")


def _template_body(wikitext: str, name: str) -> str:
    match = re.search(r"\{\{\s*" + re.escape(name) + r"(?=\s|\||\}\})", wikitext, re.IGNORECASE)
    if match is None:
        raise DataUnavailableError(f"Pinned page has no {name!r} template")
    cursor = match.end()
    depth = 1
    while cursor < len(wikitext) - 1:
        pair = wikitext[cursor : cursor + 2]
        if pair == "{{":
            depth += 1
            cursor += 2
            continue
        if pair == "}}":
            depth -= 1
            if depth == 0:
                return wikitext[match.end() : cursor]
            cursor += 2
            continue
        cursor += 1
    raise DataUnavailableError(f"Unclosed {name!r} template in pinned page")


def _split_top_level(body: str) -> list[str]:
    parts: list[str] = []
    start = 0
    brace_depth = 0
    link_depth = 0
    cursor = 0
    while cursor < len(body):
        pair = body[cursor : cursor + 2]
        if pair == "{{":
            brace_depth += 1
            cursor += 2
            continue
        if pair == "}}" and brace_depth:
            brace_depth -= 1
            cursor += 2
            continue
        if pair == "[[":
            link_depth += 1
            cursor += 2
            continue
        if pair == "]]" and link_depth:
            link_depth -= 1
            cursor += 2
            continue
        if body[cursor] == "|" and not brace_depth and not link_depth:
            parts.append(body[start:cursor])
            start = cursor + 1
        cursor += 1
    parts.append(body[start:])
    return parts


def parse_template(wikitext: str, name: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in _split_top_level(_template_body(wikitext, name)):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        if key:
            fields[key] = value.strip()
    return fields


def _plain(value: str) -> str:
    value = re.sub(r"<!--.*?-->", "", value, flags=re.DOTALL)
    value = re.sub(
        rf"\{{\{{SCP\|({_SKILLS})\|(\d+)(?:\|[^{{}}]*)?\}}\}}",
        r"\2 \1",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"\{\{[^{}]*\}\}", "", value)
    return value.strip()


def _integer(value: str, field: str) -> int:
    cleaned = _plain(value).replace("−", "-")
    match = _INTEGER.match(cleaned)
    if match is None:
        raise DataUnavailableError(f"Equipment field {field!r} is not an exact integer: {value!r}")
    return int(match.group(1).replace(",", ""))


def _yes_no(value: str, field: str) -> bool:
    cleaned = _plain(value).casefold()
    if cleaned == "yes":
        return True
    if cleaned == "no":
        return False
    raise DataUnavailableError(f"Equipment field {field!r} is not an exact Yes/No claim: {value!r}")


_REQUIREMENT_CUE = re.compile(r"\b(?:requir\w*|wear\w*|worn|wield\w*|equip\w*)\b", re.IGNORECASE)
_SKILL_LIST = rf"(?:{_SKILLS})(?:\s*(?:,|and|or|/|&)\s*(?:{_SKILLS}))*"
# "40 Defence", "level 40 Ranged and Defence", "20 Ranged, Defence and Strength"
_LEVEL_THEN_SKILLS = re.compile(rf"(?:level\s+)?(\d+)\s+({_SKILL_LIST})\b", re.IGNORECASE)
# "a Defence level of 40", "Defence level of at least 40", "Attack level 30"
_SKILL_THEN_LEVEL = re.compile(rf"({_SKILLS})\s+level\s+(?:of\s+)?(?:at\s+least\s+)?(\d+)\b", re.IGNORECASE)
# "level 20 in Strength"
_LEVEL_IN_SKILL = re.compile(rf"level\s+(\d+)\s+in\s+({_SKILLS})\b", re.IGNORECASE)
_SKILL_WORD = re.compile(_SKILLS, re.IGNORECASE)
# Sentences about somewhere or something else: building entry, comparisons with other gear.
_NOT_THIS_ITEM = re.compile(r"\b(?:to\s+enter|lack\w*|alternative\s+to|compared)\b|no\s+requirements?", re.IGNORECASE)


def _is_bonus_mention(sentence: str, match: re.Match[str]) -> bool:
    """`-64 Magic attack bonus` is an equipment stat, not a level requirement."""
    if match.start() > 0 and sentence[match.start() - 1] in "-+":
        return True
    return bool(re.match(r"\s+(?:attack|defence|strength|bonus)", sentence[match.end() :], re.IGNORECASE))


def _lead_section(plain: str) -> str:
    """Prose before the first `== heading ==`; wiki pages state equip requirements there."""
    return re.split(r"\n==", plain, maxsplit=1)[0]


def _requirements(wikitext: str) -> dict[str, int]:
    """Skill requirements stated in the page lead, in any of the wiki's usual phrasings.

    Only sentences that talk about requiring, wearing, wielding or equipping are
    read, so Smithing recipe sentences and comparisons with other items are ignored.
    A shared level applies to every skill in a list ("20 Ranged and Defence").
    """
    requirements: dict[str, int] = {}

    def apply(skill: str, level: str) -> None:
        key = skill.casefold()
        requirements[key] = max(requirements.get(key, 0), int(level))

    for sentence in re.split(r"(?<=[.!?])\s+", _lead_section(_plain(wikitext))):
        if not _REQUIREMENT_CUE.search(sentence) or _NOT_THIS_ITEM.search(sentence):
            continue
        for match in _LEVEL_THEN_SKILLS.finditer(sentence):
            if _is_bonus_mention(sentence, match):
                continue
            for skill in _SKILL_WORD.findall(match.group(2)):
                apply(skill, match.group(1))
        for match in _SKILL_THEN_LEVEL.finditer(sentence):
            apply(match.group(1), match.group(2))
        for match in _LEVEL_IN_SKILL.finditer(sentence):
            apply(match.group(2), match.group(1))
    return requirements


@dataclass(frozen=True)
class WikiItemObservation:
    item_id: int
    name: str
    free_to_play: bool
    members: bool
    equipable: bool
    slot: str
    requirements: Mapping[str, int]
    bonuses: Mapping[str, int]
    attack_speed: int | None
    attack_range: int | None
    combat_style: str | None
    source_ids: tuple[str, ...]
    status: str
    verification_gaps: tuple[str, ...]
    environment_scope: str | None = None

    def to_document(self) -> dict[str, Any]:
        return asdict(self)


# The wiki writes ``attackrange = staff`` for staves: a melee-range (1 tile) bash whose
# spells use the spell's own range.  Every other value is an exact integer.
_STAFF_RANGE = 1


def _attack_range(value: str | None) -> int | None:
    if not value:
        return None
    if _plain(value).casefold() == "staff":
        return _STAFF_RANGE
    return _integer(value, "attackrange")


def observe_equipment(record: Mapping[str, Any]) -> WikiItemObservation:
    """Extract source observations without silently promoting them to game truth.

    The parser handles data visible in the page's Infobox templates. Fields not
    proven there remain explicit verification gaps, so the legality engine will
    reject the record until a later evidence-backed promotion step.
    """
    content = record.get("content")
    if not isinstance(content, str):
        raise DataUnavailableError("Wiki source record is missing raw wikitext")
    item = parse_template(content, "Infobox Item")
    bonuses = parse_template(content, "Infobox Bonuses")
    try:
        version = int(item.get("defver", "1"))
    except ValueError as error:
        raise DataUnavailableError("Infobox Item defver is not an integer") from error

    def item_field(name: str) -> str | None:
        return item.get(name) or item.get(f"{name}{version}")

    required_item_fields = {"id", "name", "members", "equipable"}
    required_bonus_fields = {
        "astab",
        "aslash",
        "acrush",
        "amagic",
        "arange",
        "dstab",
        "dslash",
        "dcrush",
        "dmagic",
        "drange",
        "str",
        "rstr",
        "mdmg",
        "prayer",
        "slot",
    }
    missing = {field for field in required_item_fields if item_field(field) is None} | (
        required_bonus_fields - set(bonuses)
    )
    if missing:
        raise DataUnavailableError(f"Pinned equipment page omits required template fields: {sorted(missing)}")
    is_members = _yes_no(item_field("members") or "", "members")
    equipable = _yes_no(item_field("equipable") or "", "equipable")
    parsed_bonuses = {
        "attack_stab": _integer(bonuses["astab"], "astab"),
        "attack_slash": _integer(bonuses["aslash"], "aslash"),
        "attack_crush": _integer(bonuses["acrush"], "acrush"),
        "attack_magic": _integer(bonuses["amagic"], "amagic"),
        "attack_ranged": _integer(bonuses["arange"], "arange"),
        "defence_stab": _integer(bonuses["dstab"], "dstab"),
        "defence_slash": _integer(bonuses["dslash"], "dslash"),
        "defence_crush": _integer(bonuses["dcrush"], "dcrush"),
        "defence_magic": _integer(bonuses["dmagic"], "dmagic"),
        "defence_ranged": _integer(bonuses["drange"], "drange"),
        "melee_strength": _integer(bonuses["str"], "str"),
        "ranged_strength": _integer(bonuses["rstr"], "rstr"),
        "magic_damage": _integer(bonuses["mdmg"], "mdmg"),
        "prayer": _integer(bonuses["prayer"], "prayer"),
    }
    source_id = record.get("source_id")
    if not isinstance(source_id, str) or not source_id.strip():
        raise DataUnavailableError("Wiki source record is missing its source ID")
    gaps = ["obtainability", "availability_scope", "skill_requirements", "quest_requirements"]
    if bonuses["slot"].strip().casefold() in {"weapon", "2h"}:
        gaps.extend(["ammo_compatibility", "special_mechanics", "verified_attack_styles"])
    source_title = record.get("title")
    scope_text = " ".join(value for value in (item_field("name"), source_title) if isinstance(value, str)).casefold()
    environment_scope = "lms_or_deadman" if any(marker in scope_text for marker in _OUT_OF_SCOPE_MARKERS) else None
    return WikiItemObservation(
        item_id=_integer(item_field("id") or "", "id"),
        name=_plain(item_field("name") or ""),
        free_to_play=not is_members,
        members=is_members,
        equipable=equipable,
        slot=bonuses["slot"].strip().casefold(),
        requirements=_requirements(content),
        bonuses=parsed_bonuses,
        attack_speed=_integer(bonuses["speed"], "speed") if bonuses.get("speed") else None,
        attack_range=_attack_range(bonuses.get("attackrange")),
        combat_style=_plain(bonuses["combatstyle"]) if bonuses.get("combatstyle") else None,
        source_ids=(source_id,),
        status="observed",
        verification_gaps=tuple(gaps),
        environment_scope=environment_scope,
    )
