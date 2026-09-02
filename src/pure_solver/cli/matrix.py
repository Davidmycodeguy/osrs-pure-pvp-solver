"""Gear-matrix subcommands: enumerate verified loadout rows per unlock band or exact account, then screen them.

Commands: ``export-gear-matrix``, ``export-exact-gear-matrix`` and ``screen-gear-matrix``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..accounts import AccountSearchBounds, LevelRange
from ..gear_matrix import (
    build_exact_account_gear_matrix,
    build_verified_gear_matrix,
    write_verified_gear_matrix_csv,
    write_verified_gear_matrix_json,
)
from ..gear_screen import screen_gear_matrix_csv
from ..legality import EquipmentItem
from ..ruleset import load_ruleset
from .common import ACCOUNT_MODES, SubcommandGroup, add_level_range


def _export_gear_matrix(args: argparse.Namespace) -> int:
    ruleset = load_ruleset(args.ruleset)
    items = tuple(EquipmentItem.from_document(item) for item in ruleset.items)
    matrix = build_verified_gear_matrix(items, maximum_level=args.maximum_level)
    write_verified_gear_matrix_json(matrix, args.json_output)
    write_verified_gear_matrix_csv(matrix, args.csv_output)
    print(
        json.dumps(
            {
                "json_output": str(args.json_output),
                "csv_output": str(args.csv_output),
                "maximum_level": args.maximum_level,
                "profile_count": matrix.profile_count,
                "combination_count": matrix.combination_count,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def register_export_gear_matrix(commands: SubcommandGroup) -> None:
    export_matrix = commands.add_parser(
        "export-gear-matrix",
        help="export verified F2P head/neck/body/legs/hands/weapon combinations with derived ammo and shield",
    )
    export_matrix.add_argument("ruleset", type=Path)
    export_matrix.add_argument("--maximum-level", type=int, default=40)
    export_matrix.add_argument("--json-output", type=Path, required=True)
    export_matrix.add_argument("--csv-output", type=Path, required=True)
    export_matrix.set_defaults(handler=_export_gear_matrix)


def _export_exact_gear_matrix(args: argparse.Namespace) -> int:
    ruleset = load_ruleset(args.ruleset)
    items = tuple(EquipmentItem.from_document(item) for item in ruleset.items)
    bounds = AccountSearchBounds(
        attack=LevelRange(args.attack_min, args.attack_max),
        strength=LevelRange(args.strength_min, args.strength_max),
        ranged=LevelRange(args.ranged_min, args.ranged_max),
        magic=LevelRange(args.magic_min, args.magic_max),
        prayer=LevelRange(args.prayer_min, args.prayer_max),
        hitpoints=LevelRange(args.hitpoints_min, args.hitpoints_max),
        combat_minimum=args.combat_min,
        combat_maximum=args.combat_max,
    )
    matrix = build_exact_account_gear_matrix(
        items,
        ruleset.mechanics,
        bounds,
        max_candidates=args.max_candidates,
        account_mode=args.account_mode,
    )
    write_verified_gear_matrix_json(matrix, args.json_output)
    write_verified_gear_matrix_csv(matrix, args.csv_output)
    print(
        json.dumps(
            {
                "json_output": str(args.json_output),
                "csv_output": str(args.csv_output),
                "profile_count": matrix.profile_count,
                "combination_count": matrix.combination_count,
                "account_mode": args.account_mode,
                "combat_minimum": args.combat_min,
                "combat_maximum": args.combat_max,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def register_export_exact_gear_matrix(commands: SubcommandGroup) -> None:
    exact_matrix = commands.add_parser(
        "export-exact-gear-matrix",
        help="export verified combinations for exact achievable accounts in a combat/stat range",
    )
    exact_matrix.add_argument("ruleset", type=Path)
    add_level_range(exact_matrix, "attack", minimum=1, maximum=40)
    add_level_range(exact_matrix, "strength", minimum=1, maximum=40)
    add_level_range(exact_matrix, "ranged", minimum=1, maximum=40)
    add_level_range(exact_matrix, "magic", minimum=1, maximum=40)
    add_level_range(exact_matrix, "prayer", minimum=1, maximum=40)
    add_level_range(exact_matrix, "hitpoints", minimum=10, maximum=99)
    add_level_range(exact_matrix, "combat", minimum=30, maximum=40)
    exact_matrix.add_argument("--account-mode", choices=ACCOUNT_MODES, default="f2p_standard_training")
    exact_matrix.add_argument("--max-candidates", type=int)
    exact_matrix.add_argument("--json-output", type=Path, required=True)
    exact_matrix.add_argument("--csv-output", type=Path, required=True)
    exact_matrix.set_defaults(handler=_export_exact_gear_matrix)


def _screen_gear_matrix(args: argparse.Namespace) -> int:
    ruleset = load_ruleset(args.ruleset)
    ruleset.verify_source_archive()
    items = tuple(EquipmentItem.from_document(document) for document in ruleset.items)
    report = screen_gear_matrix_csv(
        args.input,
        items,
        seed_size=args.seed_size,
        audit_limit=args.audit_limit,
    )
    document = report.to_document()
    encoded = json.dumps(document, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    **document["counts"],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(encoded)
    return 0


def register_screen_gear_matrix(commands: SubcommandGroup) -> None:
    screen_matrix = commands.add_parser(
        "screen-gear-matrix",
        help="conservatively reduce a verified full-loadout matrix and choose diverse simulator seeds",
    )
    screen_matrix.add_argument("ruleset", type=Path)
    screen_matrix.add_argument("input", type=Path, help="CSV produced by export-gear-matrix")
    screen_matrix.add_argument("--seed-size", type=int, default=32)
    screen_matrix.add_argument("--audit-limit", type=int, default=20)
    screen_matrix.add_argument("--output", type=Path)
    screen_matrix.set_defaults(handler=_screen_gear_matrix)
