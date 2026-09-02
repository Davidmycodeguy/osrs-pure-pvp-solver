"""Command-line interface for ``pure_solver`` (``python -m pure_solver`` or the ``pure-solver`` script).

Subcommand handlers live in the sibling modules, grouped by theme; :mod:`.parser` wires them into one
:mod:`argparse` parser in a fixed order and exposes :func:`main`.
"""

from .parser import build_parser, main

__all__ = ["build_parser", "main"]
