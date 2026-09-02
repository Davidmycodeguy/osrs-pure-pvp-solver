"""Duel-solver subcommands that run the bounded melee/ranged duel engine over executable strategies.

Commands: ``solve`` (explicit strategy budget) and ``solve-active`` (sparse two-sided double oracle). Both
emit a machine-readable ``blocked`` payload and exit 2 when a required mechanic is missing.
"""

from __future__ import annotations

import argparse
import json
from fractions import Fraction
from pathlib import Path

from ..accounts import LevelRange
from ..active_solver import solve_supported_active_strategy_space
from ..errors import SolverError
from ..ruleset import load_ruleset
from ..solver import DUEL_REQUIRED_MECHANICS, solve_supported_strategy_space
from .common import ACCOUNT_MODES, SubcommandGroup, add_level_range, apply_wiki_first_mode


def _add_duel_search_arguments(parser: argparse.ArgumentParser) -> None:
    """Options shared by ``solve`` and ``solve-active``: ruleset, level bounds and the duel sampling budget."""
    parser.add_argument("ruleset", type=Path)
    add_level_range(parser, "attack", minimum=1, maximum=40)
    add_level_range(parser, "strength", minimum=1, maximum=60)
    add_level_range(parser, "ranged", minimum=1, maximum=60)
    parser.add_argument("--prayer-max", type=int, default=43)
    add_level_range(parser, "hitpoints", minimum=10, maximum=99)
    add_level_range(parser, "combat", minimum=30, maximum=40)
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--maximum-ticks", type=int, default=200)
    parser.add_argument("--max-candidates", type=int, default=1, help="explicit account-search budget")


def _add_duel_output_arguments(parser: argparse.ArgumentParser) -> None:
    """Trailing options shared by ``solve`` and ``solve-active``: account mode, wiki-first mode and output."""
    parser.add_argument("--account-mode", choices=ACCOUNT_MODES, default="f2p_standard_training")
    parser.add_argument(
        "--wiki-first",
        action="store_true",
        help="allow provisional non-verified wiki items from the ruleset source archive",
    )
    parser.add_argument("--output", type=Path)


def _solve(args: argparse.Namespace) -> int:
    ruleset = load_ruleset(args.ruleset)
    if args.wiki_first:
        ruleset = apply_wiki_first_mode(ruleset)
    try:
        report = solve_supported_strategy_space(
            ruleset,
            attack_range=LevelRange(args.attack_min, args.attack_max),
            strength_range=LevelRange(args.strength_min, args.strength_max),
            ranged_range=LevelRange(args.ranged_min, args.ranged_max),
            prayer_range=LevelRange(1, args.prayer_max),
            hitpoints_range=LevelRange(args.hitpoints_min, args.hitpoints_max),
            combat_minimum=args.combat_min,
            combat_maximum=args.combat_max,
            samples=args.samples,
            seed=args.seed,
            maximum_ticks=args.maximum_ticks,
            maximum_accounts=args.max_candidates,
            maximum_strategies=args.max_strategies,
            account_mode=args.account_mode,
            allow_wiki_first=args.wiki_first,
        )
    except SolverError as error:
        # A timing gate is not a partial duel result.  Emit machine-readable
        # status so callers can distinguish a verified answer from a blocked
        # search without pretending the offense frontier solved the game.
        payload = {
            "scope": "melee_ranged_duel_strategy_v1",
            "reproducibility_metadata": dict(ruleset.reproducibility_metadata),
            "verification": {
                "status": "blocked",
                "production_ready": False,
                "required_mechanics": DUEL_REQUIRED_MECHANICS,
                "allow_wiki_first": args.wiki_first,
                "error_type": type(error).__name__,
                "message": str(error),
            },
        }
        encoded = json.dumps(payload, indent=2, sort_keys=True)
        if args.output:
            args.output.write_text(encoded + "\n", encoding="utf-8")
        print(encoded)
        return 2
    encoded = json.dumps(report.to_document(), indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
        print(json.dumps({"output": str(args.output), "strategies": report.search.strategy_count}, indent=2))
    else:
        print(encoded)
    return 0


def register_solve(commands: SubcommandGroup) -> None:
    solve = commands.add_parser("solve", help="solve a bounded, strategy-aware melee/ranged duel game")
    _add_duel_search_arguments(solve)
    solve.add_argument("--max-strategies", type=int, default=32, help="bounded number of materialized strategies")
    _add_duel_output_arguments(solve)
    solve.set_defaults(handler=_solve)


def _solve_active(args: argparse.Namespace) -> int:
    ruleset = load_ruleset(args.ruleset)
    if args.wiki_first:
        ruleset = apply_wiki_first_mode(ruleset)
    try:
        report = solve_supported_active_strategy_space(
            ruleset,
            attack_range=LevelRange(args.attack_min, args.attack_max),
            strength_range=LevelRange(args.strength_min, args.strength_max),
            ranged_range=LevelRange(args.ranged_min, args.ranged_max),
            prayer_range=LevelRange(1, args.prayer_max),
            hitpoints_range=LevelRange(args.hitpoints_min, args.hitpoints_max),
            combat_minimum=args.combat_min,
            combat_maximum=args.combat_max,
            samples=args.samples,
            seed=args.seed,
            maximum_ticks=args.maximum_ticks,
            maximum_accounts=args.max_candidates,
            candidate_pool_size=args.candidate_pool_size,
            initial_active_size=args.initial_active_size,
            outside_batch_size=args.outside_batch_size,
            oracle_epsilon=Fraction(str(args.oracle_epsilon)),
            oracle_max_iterations=args.oracle_max_iterations,
            account_mode=args.account_mode,
            allow_wiki_first=args.wiki_first,
        )
    except SolverError as error:
        payload = {
            "scope": "bounded_melee_ranged_pairwise_restricted_grid_double_oracle_v1",
            "reproducibility_metadata": dict(ruleset.reproducibility_metadata),
            "verification": {
                "status": "blocked",
                "production_ready": False,
                "perfect_play_claim": False,
                "required_mechanics": DUEL_REQUIRED_MECHANICS,
                "error_type": type(error).__name__,
                "message": str(error),
            },
        }
        encoded = json.dumps(payload, indent=2, sort_keys=True)
        if args.output:
            args.output.write_text(encoded + "\n", encoding="utf-8")
        print(encoded)
        return 2
    document = report.to_document()
    encoded = json.dumps(document, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "candidate_pool_count": document["verification"]["candidate_pool_count"],
                    "initial_active_count": document["verification"]["initial_active_count"],
                    "final_active_count": document["verification"]["final_active_count"],
                    "directed_simulator_solves": document["verification"]["directed_simulator_solves"],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(encoded)
    return 0


def register_solve_active(commands: SubcommandGroup) -> None:
    solve_active = commands.add_parser(
        "solve-active",
        help="run a bounded restricted-policy duel pool through a sparse two-sided double oracle",
    )
    _add_duel_search_arguments(solve_active)
    solve_active.add_argument("--candidate-pool-size", type=int, default=256)
    solve_active.add_argument("--initial-active-size", type=int, default=32)
    solve_active.add_argument("--outside-batch-size", type=int, default=24)
    solve_active.add_argument("--oracle-epsilon", type=float, default=0.02)
    solve_active.add_argument("--oracle-max-iterations", type=int, default=12)
    _add_duel_output_arguments(solve_active)
    solve_active.set_defaults(handler=_solve_active)
