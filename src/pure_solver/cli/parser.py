"""Top-level ``argparse`` wiring: the subcommand registration order, :func:`build_parser` and :func:`main`."""

from __future__ import annotations

import argparse
import sys

from ..errors import SolverError
from . import audit, data, matrix, offense, pipeline, solve

# Registration order is the order subcommands are listed in ``--help``; keep it stable.
_SUBCOMMANDS = (
    data.register_inspect,
    data.register_fetch_wiki_page,
    data.register_observe_wiki_item,
    data.register_add_items,
    data.register_rebuild_items,
    data.register_rebuild_consumables,
    data.register_observe_wiki_search,
    audit.register_gear_audit,
    audit.register_catalog_audit,
    audit.register_export_gear_catalog,
    matrix.register_export_gear_matrix,
    matrix.register_export_exact_gear_matrix,
    pipeline.register_account_frontier,
    pipeline.register_export_account_gear_matrix,
    pipeline.register_select_top_accounts,
    matrix.register_screen_gear_matrix,
    pipeline.register_screen_resolved_gear_matrix,
    pipeline.register_rank_resolved_survivors,
    offense.register_offense_frontier,
    audit.register_validate_timing_experiment,
    offense.register_merge_frontiers,
    solve.register_solve,
    solve.register_solve_active,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OSRS F2P pure solver core")
    commands = parser.add_subparsers(dest="command", required=True)
    for register in _SUBCOMMANDS:
        register(commands)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except SolverError as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 2
