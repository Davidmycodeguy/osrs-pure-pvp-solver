"""Data-collection subcommands: inspect a ruleset, pin OSRS Wiki revisions, and rebuild verified item data.

Commands: ``inspect``, ``fetch-wiki-page``, ``observe-wiki-item``, ``add-items``, ``rebuild-items``,
``rebuild-consumables`` and ``observe-wiki-search``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..add_items import DEFAULT_TITLES, add_items, format_table
from ..canonical import canonical_hash
from ..consumable_verification import build_verified_consumable_documents
from ..errors import SolverError
from ..item_verification import build_verified_item_documents
from ..potion_verification import build_verified_potion_documents
from ..ruleset import load_ruleset
from ..sources import fetch_wiki_revision, fetch_wiki_search_revisions, write_source_record
from ..wiki_items import observe_equipment
from .common import SubcommandGroup


def _inspect(args: argparse.Namespace) -> int:
    ruleset = load_ruleset(args.ruleset)
    result = dict(ruleset.reproducibility_metadata)
    try:
        ruleset.preflight()
    except SolverError as error:
        result.update({"production_ready": False, "preflight_error": type(error).__name__, "message": str(error)})
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    result["production_ready"] = True
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def register_inspect(commands: SubcommandGroup) -> None:
    inspect = commands.add_parser("inspect", help="validate a ruleset and print reproducibility metadata")
    inspect.add_argument("ruleset", type=Path)
    inspect.set_defaults(handler=_inspect)


def _fetch_wiki_page(args: argparse.Namespace) -> int:
    record = fetch_wiki_revision(args.title)
    write_source_record(record, args.output)
    print(json.dumps({key: value for key, value in record.items() if key != "content"}, indent=2, sort_keys=True))
    return 0


def register_fetch_wiki_page(commands: SubcommandGroup) -> None:
    fetch = commands.add_parser("fetch-wiki-page", help="fetch and preserve one revision from the OSRS Wiki API")
    fetch.add_argument("title")
    fetch.add_argument("output", type=Path)
    fetch.set_defaults(handler=_fetch_wiki_page)


def _observe_wiki_item(args: argparse.Namespace) -> int:
    record = fetch_wiki_revision(args.title)
    observation = observe_equipment(record).to_document()
    payload = {"source": {key: value for key, value in record.items() if key != "content"}, "observation": observation}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def register_observe_wiki_item(commands: SubcommandGroup) -> None:
    observe = commands.add_parser(
        "observe-wiki-item", help="extract an unpromoted item observation from a pinned Wiki page"
    )
    observe.add_argument("title")
    observe.add_argument("output", type=Path)
    observe.set_defaults(handler=_observe_wiki_item)


def _add_items(args: argparse.Namespace) -> int:
    titles = tuple(args.titles) if args.titles else DEFAULT_TITLES
    rows = add_items(args.ruleset, titles, fetch=not args.no_fetch)
    print(format_table(rows))
    print(
        json.dumps(
            {
                "added": sum(1 for row in rows if row.outcome.startswith("added")),
                "skipped": sum(1 for row in rows if row.outcome.startswith("skipped")),
                "already": sum(1 for row in rows if row.outcome == "already verified"),
            }
        )
    )
    return 0


def register_add_items(commands: SubcommandGroup) -> None:
    add = commands.add_parser(
        "add-items",
        help=(
            "archive, register, verify and rebuild equipment from OSRS Wiki pages "
            "(default: F2P Defence armour and staves)"
        ),
    )
    add.add_argument("ruleset", type=Path)
    add.add_argument("titles", nargs="*")
    add.add_argument("--no-fetch", action="store_true", help="only use pages already in the source archive")
    add.set_defaults(handler=_add_items)


def _rebuild_items(args: argparse.Namespace) -> int:
    ruleset = load_ruleset(args.ruleset)
    try:
        decisions = json.loads(args.decisions.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read item verification decisions: {args.decisions}") from error
    if ruleset.source_archive is None:
        raise ValueError("Ruleset has no source archive")
    documents = build_verified_item_documents(
        ruleset.source_archive,
        decisions,
        set(ruleset.mechanics.source_revisions),
    )
    output = args.output or (args.ruleset / "items.json")
    output.write_text(json.dumps(documents, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"items": len(documents), "output": str(output)}, indent=2))
    return 0


def register_rebuild_items(commands: SubcommandGroup) -> None:
    rebuild = commands.add_parser(
        "rebuild-items", help="regenerate verified item data from pinned sources and review decisions"
    )
    rebuild.add_argument("ruleset", type=Path)
    rebuild.add_argument("decisions", type=Path)
    rebuild.add_argument("--output", type=Path)
    rebuild.set_defaults(handler=_rebuild_items)


def _rebuild_consumables(args: argparse.Namespace) -> int:
    ruleset = load_ruleset(args.ruleset)
    try:
        decisions = json.loads(args.decisions.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read consumable verification decisions: {args.decisions}") from error
    if ruleset.source_archive is None:
        raise ValueError("Ruleset has no source archive")
    documents = build_verified_consumable_documents(
        ruleset.source_archive, decisions, set(ruleset.mechanics.source_revisions)
    )
    documents.extend(
        build_verified_potion_documents(ruleset.source_archive, decisions, set(ruleset.mechanics.source_revisions))
    )
    documents.sort(key=lambda item: item["consumable_id"])
    output = args.output or (args.ruleset / "consumables.json")
    output.write_text(json.dumps(documents, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"consumables": len(documents), "output": str(output)}, indent=2))
    return 0


def register_rebuild_consumables(commands: SubcommandGroup) -> None:
    rebuild_food = commands.add_parser(
        "rebuild-consumables", help="regenerate consumable data from pinned sources and review decisions"
    )
    rebuild_food.add_argument("ruleset", type=Path)
    rebuild_food.add_argument("decisions", type=Path)
    rebuild_food.add_argument("--output", type=Path)
    rebuild_food.set_defaults(handler=_rebuild_consumables)


def _observe_wiki_search(args: argparse.Namespace) -> int:
    observations: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    for record in fetch_wiki_search_revisions(args.query, maximum_records=args.limit):
        try:
            observed = observe_equipment(record).to_document()
        except Exception as error:
            failures.append(
                {
                    "title": str(record.get("title", "")),
                    "revision": str(record.get("revision", "")),
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            continue
        observations.append(
            {
                "source": {key: value for key, value in record.items() if key != "content"},
                "observation": observed,
            }
        )
    payload = {
        "query": args.query,
        "observation_count": len(observations),
        "failure_count": len(failures),
        "observations": observations,
        "failures": failures,
    }
    payload["observation_snapshot_id"] = canonical_hash(
        {
            "query": args.query,
            "observations": observations,
            "failures": failures,
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "query": args.query,
                "observations": len(observations),
                "failures": len(failures),
                "output": str(args.output),
            },
            indent=2,
        )
    )
    return 0


def register_observe_wiki_search(commands: SubcommandGroup) -> None:
    observe_search = commands.add_parser(
        "observe-wiki-search", help="extract unpromoted equipment observations for a Wiki search"
    )
    observe_search.add_argument("query")
    observe_search.add_argument("output", type=Path)
    observe_search.add_argument("--limit", type=int)
    observe_search.set_defaults(handler=_observe_wiki_search)
