"""Helpers shared by the ``pure_solver.cli`` subcommand modules."""

from __future__ import annotations

import argparse
from dataclasses import replace

from ..item_verification import build_wiki_trusted_item_documents
from ..ruleset import Ruleset

# The object returned by ``ArgumentParser.add_subparsers()``; every ``register_*`` function takes one.
SubcommandGroup = argparse._SubParsersAction

ACCOUNT_MODES = ("f2p_standard_training", "independent_hp")


def add_level_range(parser: argparse.ArgumentParser, name: str, *, minimum: int, maximum: int) -> None:
    """Register ``--<name>-min`` and ``--<name>-max`` integer options with the given defaults."""
    parser.add_argument(f"--{name}-min", type=int, default=minimum)
    parser.add_argument(f"--{name}-max", type=int, default=maximum)


def apply_wiki_first_mode(ruleset: Ruleset) -> Ruleset:
    """Return a copy of ``ruleset`` whose item table also carries provisional wiki-trusted items.

    Verified items always win; a provisional document only fills an item ID the ruleset does not know.
    """
    if ruleset.source_archive is None:
        raise ValueError("Ruleset has no source archive")
    provisional = build_wiki_trusted_item_documents(ruleset.source_archive)
    merged = {document["item_id"]: document for document in ruleset.items}
    for document in provisional:
        merged.setdefault(document["item_id"], document)
    return replace(ruleset, items=tuple(merged.values()))
