"""Closed-form offense-frontier subcommands: rank verified account/kit pairs against a fixed target, then merge shards.

Commands: ``offense-frontier`` and ``merge-frontiers``. This lane reports offensive output only; it is not the
full duel ranking.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..accounts import LevelRange
from ..frontier import OffensiveTarget, solve_verified_offense
from ..frontier_merge import merge_offense_frontiers
from ..ruleset import load_ruleset
from .common import ACCOUNT_MODES, SubcommandGroup, add_level_range, read_json_document


def _offense_frontier(args: argparse.Namespace) -> int:
    ruleset = load_ruleset(args.ruleset)
    result = solve_verified_offense(
        ruleset,
        target=OffensiveTarget(
            defence_level=args.target_defence,
            stab_defence_bonus=args.target_stab,
            slash_defence_bonus=args.target_slash,
            crush_defence_bonus=args.target_crush,
            ranged_defence_bonus=args.target_ranged,
        ),
        attack_range=LevelRange(args.attack_min, args.attack_max),
        strength_range=LevelRange(args.strength_min, args.strength_max),
        ranged_range=LevelRange(args.ranged_min, args.ranged_max),
        prayer_maximum=args.prayer_max,
        hitpoints_range=LevelRange(args.hitpoints_min, args.hitpoints_max),
        combat_minimum=args.combat_min,
        combat_maximum=args.combat_max,
        top=args.top,
        max_candidates=args.max_candidates,
        account_mode=args.account_mode,
    )
    encoded = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
        print(json.dumps({"output": str(args.output), "top": len(result["top_overall"])}, indent=2))
    else:
        print(encoded)
    return 0


def register_offense_frontier(commands: SubcommandGroup) -> None:
    frontier = commands.add_parser(
        "offense-frontier", help="run the verified closed-form offense frontier (not full duel ranking)"
    )
    frontier.add_argument("ruleset", type=Path)
    add_level_range(frontier, "attack", minimum=1, maximum=40)
    add_level_range(frontier, "strength", minimum=1, maximum=60)
    add_level_range(frontier, "ranged", minimum=1, maximum=60)
    frontier.add_argument("--prayer-max", type=int, default=43)
    add_level_range(frontier, "hitpoints", minimum=10, maximum=99)
    add_level_range(frontier, "combat", minimum=30, maximum=40)
    frontier.add_argument("--target-defence", type=int, default=1)
    frontier.add_argument("--target-stab", type=int, default=0)
    frontier.add_argument("--target-slash", type=int, default=0)
    frontier.add_argument("--target-crush", type=int, default=0)
    frontier.add_argument("--target-ranged", type=int, default=0)
    frontier.add_argument("--top", type=int, default=10)
    frontier.add_argument("--max-candidates", type=int)
    frontier.add_argument("--account-mode", choices=ACCOUNT_MODES, default="f2p_standard_training")
    frontier.add_argument("--output", type=Path)
    frontier.set_defaults(handler=_offense_frontier)


def _merge_frontiers(args: argparse.Namespace) -> int:
    documents = []
    for path in args.inputs:
        documents.append(read_json_document(path, "frontier shard"))
    merged = merge_offense_frontiers(documents, top=args.top)
    args.output.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "shards": len(documents),
                "top": len(merged["top_overall"]),
            },
            indent=2,
        )
    )
    return 0


def register_merge_frontiers(commands: SubcommandGroup) -> None:
    merge = commands.add_parser(
        "merge-frontiers", help="merge combat-level frontier shards with identical catalog scope"
    )
    merge.add_argument("output", type=Path)
    merge.add_argument("inputs", nargs="+", type=Path)
    merge.add_argument("--top", type=int, default=10)
    merge.set_defaults(handler=_merge_frontiers)
