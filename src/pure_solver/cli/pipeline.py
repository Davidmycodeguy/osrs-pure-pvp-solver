"""Staged account-pipeline subcommands (Stages 1-4), the reference that ``pure_math`` reproduces byte for byte.

Commands: ``account-frontier`` (Stage 1), ``export-account-gear-matrix`` (Stage 2),
``screen-resolved-gear-matrix`` (Stage 3), ``rank-resolved-survivors`` (Stage 4) and
``select-top-accounts`` (collects the accounts behind the best-ranked rows for a full-gear re-run).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..account_frontier import (
    build_account_frontier,
    read_account_frontier_csv,
    top_ranked_accounts,
    write_account_frontier_csv,
    write_account_frontier_json,
)
from ..account_gear_matrix import KIT_MODES, build_account_gear_matrix
from ..gear_matrix import write_verified_gear_matrix_csv
from ..legality import EquipmentItem
from ..resolved_gear_screen import (
    screen_resolved_gear_matrix_csv,
    write_resolved_gear_report,
    write_resolved_survivor_manifest,
)
from ..ruleset import load_ruleset
from ..survivor_ranking import (
    rank_survivor_manifest,
    write_ranked_survivors_csv,
    write_survivor_ranking_report,
)
from .common import SubcommandGroup


def _account_frontier(args: argparse.Namespace) -> int:
    ruleset = load_ruleset(args.ruleset)
    frontier = build_account_frontier(ruleset.mechanics, combat_level=args.combat_level)
    write_account_frontier_csv(frontier.ranking_frontier, ruleset.mechanics, args.ranking_output)
    write_account_frontier_csv(frontier.full_frontier, ruleset.mechanics, args.full_output)
    write_account_frontier_json(frontier, args.report_output)
    print(
        json.dumps(
            {
                "ranking_output": str(args.ranking_output),
                "full_output": str(args.full_output),
                "report_output": str(args.report_output),
                **frontier.to_document()["counts"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def register_account_frontier(commands: SubcommandGroup) -> None:
    frontier = commands.add_parser(
        "account-frontier",
        help="enumerate exact combat-level 1-Defence accounts with reachable HP and verified prayer breakpoints",
    )
    frontier.add_argument("ruleset", type=Path)
    frontier.add_argument("--combat-level", type=int, default=30)
    frontier.add_argument("--ranking-output", type=Path, required=True, help="Pareto set with Magic as leftover fill")
    frontier.add_argument("--full-output", type=Path, required=True, help="Pareto set keeping Magic as a dimension")
    frontier.add_argument("--report-output", type=Path, required=True)
    frontier.set_defaults(handler=_account_frontier)


def _export_account_gear_matrix(args: argparse.Namespace) -> int:
    ruleset = load_ruleset(args.ruleset)
    items = tuple(EquipmentItem.from_document(item) for item in ruleset.items)
    accounts = read_account_frontier_csv(args.accounts)
    matrix, signature_count = build_account_gear_matrix(accounts, items, kit_mode=args.kit_mode)
    write_verified_gear_matrix_csv(matrix, args.csv_output)
    print(
        json.dumps(
            {
                "accounts": str(args.accounts),
                "csv_output": str(args.csv_output),
                "kit_mode": args.kit_mode,
                "profile_count": matrix.profile_count,
                "unlock_signature_count": signature_count,
                "combination_count": matrix.combination_count,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def register_export_account_gear_matrix(commands: SubcommandGroup) -> None:
    account_matrix = commands.add_parser(
        "export-account-gear-matrix",
        help="attach gear to exact accounts from account-frontier, cached per equipment-unlock signature",
    )
    account_matrix.add_argument("ruleset", type=Path)
    account_matrix.add_argument("accounts", type=Path, help="CSV produced by account-frontier")
    account_matrix.add_argument("--kit-mode", choices=KIT_MODES, default="offence_pareto")
    account_matrix.add_argument("--csv-output", type=Path, required=True)
    account_matrix.set_defaults(handler=_export_account_gear_matrix)


def _select_top_accounts(args: argparse.Namespace) -> int:
    ruleset = load_ruleset(args.ruleset)
    accounts = top_ranked_accounts(args.input, limit=args.limit)
    write_account_frontier_csv(accounts, ruleset.mechanics, args.output)
    print(
        json.dumps(
            {
                "input": str(args.input),
                "output": str(args.output),
                "account_count": len(accounts),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def register_select_top_accounts(commands: SubcommandGroup) -> None:
    top_accounts = commands.add_parser(
        "select-top-accounts",
        help="collect the distinct accounts behind the best-ranked rows for a full-gear re-run",
    )
    top_accounts.add_argument("ruleset", type=Path)
    top_accounts.add_argument("input", type=Path, help="CSV produced by rank-resolved-survivors")
    top_accounts.add_argument("--limit", type=int, default=50)
    top_accounts.add_argument("--output", type=Path, required=True)
    top_accounts.set_defaults(handler=_select_top_accounts)


def _screen_resolved_gear_matrix(args: argparse.Namespace) -> int:
    ruleset = load_ruleset(args.ruleset)
    ruleset.verify_source_archive()
    report = screen_resolved_gear_matrix_csv(
        args.input,
        ruleset,
        audit_limit=args.audit_limit,
    )
    write_resolved_survivor_manifest(report, args.manifest_output)
    write_resolved_gear_report(report, args.report_output)
    print(
        json.dumps(
            {
                "input": str(args.input),
                "manifest_output": str(args.manifest_output),
                "report_output": str(args.report_output),
                **report.reduction.counts.to_document(),
                "remaining_resolved_options": report.reduction.counts.remaining_pareto_candidates,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def register_screen_resolved_gear_matrix(commands: SubcommandGroup) -> None:
    resolved_matrix = commands.add_parser(
        "screen-resolved-gear-matrix",
        help="resolve exact integer combat profiles, Pareto-prune them, and persist every survivor",
    )
    resolved_matrix.add_argument("ruleset", type=Path)
    resolved_matrix.add_argument("input", type=Path, help="CSV produced by export-gear-matrix")
    resolved_matrix.add_argument("--manifest-output", type=Path, required=True)
    resolved_matrix.add_argument("--report-output", type=Path, required=True)
    resolved_matrix.add_argument("--audit-limit", type=int, default=20)
    resolved_matrix.set_defaults(handler=_screen_resolved_gear_matrix)


def _rank_resolved_survivors(args: argparse.Namespace) -> int:
    """Create a complete priority order without treating it as a prune."""
    ruleset = load_ruleset(args.ruleset)
    ruleset.verify_source_archive()
    report = rank_survivor_manifest(
        args.input,
        ruleset,
        panel_size=args.panel_size,
        food_slots=args.food_slots,
        heal_per_eat=args.heal_per_eat,
        eat_penalties=args.eat_penalties,
        preview_size=args.preview_size,
    )
    write_ranked_survivors_csv(report, args.ranked_output)
    write_survivor_ranking_report(report, args.report_output)
    counts = report.to_document()["counts"]
    print(
        json.dumps(
            {
                "input": str(args.input),
                "ranked_output": str(args.ranked_output),
                "report_output": str(args.report_output),
                **counts,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def register_rank_resolved_survivors(commands: SubcommandGroup) -> None:
    rank_resolved = commands.add_parser(
        "rank-resolved-survivors",
        aliases=["rank-resolved-candidates"],
        help="rank every resolved survivor for simulator priority without deleting any row",
    )
    rank_resolved.add_argument("ruleset", type=Path)
    rank_resolved.add_argument("input", type=Path, help="CSV produced by screen-resolved-gear-matrix")
    rank_resolved.add_argument("--ranked-output", type=Path, required=True)
    rank_resolved.add_argument("--report-output", type=Path, required=True)
    rank_resolved.add_argument("--panel-size", type=int, default=32)
    rank_resolved.add_argument("--food-slots", type=int, default=28)
    rank_resolved.add_argument("--heal-per-eat", type=int, default=14)
    rank_resolved.add_argument("--eat-penalties", type=int, nargs="+", default=(3, 0))
    rank_resolved.add_argument("--preview-size", type=int, default=50)
    rank_resolved.set_defaults(handler=_rank_resolved_survivors)
