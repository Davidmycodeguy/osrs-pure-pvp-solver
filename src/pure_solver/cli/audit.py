"""Audit and export subcommands that report on data quality without changing the ruleset.

Commands: ``gear-audit``, ``catalog-audit``, ``export-gear-catalog`` and ``validate-timing-experiment``.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from ..accounts import AccountState
from ..catalog import EquipmentCatalog
from ..experiments import derive_timing_suite_claim
from ..gear_catalog_export import (
    build_account_gear_export,
    verified_level_item_profiles,
    write_account_gear_json,
    write_level_item_matrix_csv,
    write_level_item_profiles_csv,
    write_observed_representatives_csv,
    write_verified_survivors_csv,
)
from ..kits import generate_combat_kits
from ..legality import EquipmentItem
from ..ruleset import load_ruleset
from .common import SubcommandGroup

_SKILL_OPTIONS = ("attack", "strength", "ranged", "magic", "prayer", "hitpoints")


def _gear_audit(args: argparse.Namespace) -> int:
    ruleset = load_ruleset(args.ruleset)
    account = AccountState(
        args.attack,
        args.strength,
        args.ranged,
        args.magic,
        args.prayer,
        args.hitpoints,
    )
    items = tuple(EquipmentItem.from_document(item) for item in ruleset.items)
    search = generate_combat_kits(account, items)
    payload = {
        "account_id": account.canonical_id,
        "combat_level": account.combat_level(ruleset.mechanics),
        "retained_items": [{"item_id": item.item_id, "name": item.name} for item in search.item_dominance.retained],
        "illegal_items": [
            {"item_id": item.item_id, "name": item.name} for item in search.item_dominance.rejected_illegal
        ],
        "dominance_pruning": [record.__dict__ for record in search.item_dominance.pruned],
        "combat_kits": [
            {
                "kit_id": kit.canonical_id,
                "primary_weapon": kit.primary_weapon.name,
                "ko_weapon": kit.ko_weapon.name,
                "ammunition": kit.ammunition.name if kit.ammunition else None,
                "inventory_slots": kit.inventory_slots,
                "available_inventory_slots": kit.available_inventory_slots(ruleset.inventory_slots),
            }
            for kit in search.kits
        ],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def register_gear_audit(commands: SubcommandGroup) -> None:
    gear = commands.add_parser(
        "gear-audit", help="show legal items, dominance removals, and primary/KO/ammo kits for one account"
    )
    gear.add_argument("ruleset", type=Path)
    for skill in _SKILL_OPTIONS:
        gear.add_argument(f"--{skill}", type=int, required=True)
    gear.set_defaults(handler=_gear_audit)


def _catalog_audit(args: argparse.Namespace) -> int:
    catalog = EquipmentCatalog.from_paths(
        args.snapshot,
        verified_items_path=args.ruleset / "items.json",
    )
    payload = {
        "summary": asdict(catalog.summary()),
        "validation_queue": [asdict(issue) for issue in catalog.validation_queue()],
        "promotion_queue_preview": [asdict(candidate) for candidate in catalog.promotion_queue()[: args.preview]],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def register_catalog_audit(commands: SubcommandGroup) -> None:
    catalog = commands.add_parser(
        "catalog-audit", help="summarize observation completeness; LMS/Deadman variants stay audit-only"
    )
    catalog.add_argument("ruleset", type=Path)
    catalog.add_argument("snapshot", type=Path)
    catalog.add_argument("--preview", type=int, default=20)
    catalog.set_defaults(handler=_catalog_audit)


def _export_gear_catalog(args: argparse.Namespace) -> int:
    catalog = EquipmentCatalog.from_paths(
        args.snapshot,
        verified_items_path=args.ruleset / "items.json",
    )
    account = AccountState(
        args.attack,
        args.strength,
        args.ranged,
        args.magic,
        args.prayer,
        args.hitpoints,
    )
    payload = build_account_gear_export(catalog, account)
    write_account_gear_json(payload, args.json_output)
    write_observed_representatives_csv(
        payload["observed_exact_representatives"],
        args.csv_output,
    )
    if args.survivor_csv_output:
        write_verified_survivors_csv(
            payload["verified_dominance_survivors"],
            args.survivor_csv_output,
        )
    level_profiles = None
    if args.level_profiles_output or args.level_item_matrix_output:
        level_profiles = verified_level_item_profiles(catalog.verified_items, maximum_level=40)
    if args.level_profiles_output:
        write_level_item_profiles_csv(level_profiles or (), args.level_profiles_output)
    if args.level_item_matrix_output:
        write_level_item_matrix_csv(level_profiles or (), args.level_item_matrix_output)
    print(
        json.dumps(
            {
                "json_output": str(args.json_output),
                "csv_output": str(args.csv_output),
                "survivor_csv_output": str(args.survivor_csv_output) if args.survivor_csv_output else None,
                "level_profiles_output": str(args.level_profiles_output) if args.level_profiles_output else None,
                "level_item_matrix_output": str(args.level_item_matrix_output)
                if args.level_item_matrix_output
                else None,
                "level_profile_count": len(level_profiles) if level_profiles is not None else None,
                **payload["counts"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def register_export_gear_catalog(commands: SubcommandGroup) -> None:
    export_gear = commands.add_parser(
        "export-gear-catalog",
        help="export an account-legal F2P observation cache plus verified dominance audit",
    )
    export_gear.add_argument("ruleset", type=Path)
    export_gear.add_argument("snapshot", type=Path)
    for skill in _SKILL_OPTIONS:
        export_gear.add_argument(f"--{skill}", type=int, default=40)
    export_gear.add_argument("--json-output", type=Path, required=True)
    export_gear.add_argument("--csv-output", type=Path, required=True)
    export_gear.add_argument("--survivor-csv-output", type=Path)
    export_gear.add_argument("--level-profiles-output", type=Path)
    export_gear.add_argument("--level-item-matrix-output", type=Path)
    export_gear.set_defaults(handler=_export_gear_catalog)


def _validate_timing_experiment(args: argparse.Namespace) -> int:
    try:
        document = json.loads(args.input.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read timing experiment {args.input}") from error
    claim = derive_timing_suite_claim(document, minimum_samples_per_case=args.minimum_samples)
    print(
        json.dumps(
            {
                "experiment_id": claim.experiment_id,
                "status": claim.status,
                "sample_counts": claim.sample_counts,
                "mechanics": claim.mechanic_documents(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def register_validate_timing_experiment(commands: SubcommandGroup) -> None:
    timing = commands.add_parser(
        "validate-timing-experiment", help="validate empirical traces before expanding timing coverage"
    )
    timing.add_argument("input", type=Path)
    timing.add_argument("--minimum-samples", type=int, default=20)
    timing.set_defaults(handler=_validate_timing_experiment)
