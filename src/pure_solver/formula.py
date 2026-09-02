"""Evaluator for the small exact JSON formula AST stored in ``mechanics.json``: integers and ``Fraction`` only,
never floats, so formulae stay data rather than Python source.

Ported to Rust as ``pure_math/src/formula.rs`` and cross-checked by ``pure_math/tests/formula_golden.rs``;
this module is the golden reference.
"""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction
from typing import Any

from .errors import DataUnavailableError

Number = int | Fraction


def _number(value: Any) -> Number:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, Fraction):
        return value
    if isinstance(value, Mapping) and set(value) == {"numerator", "denominator"}:
        return Fraction(int(value["numerator"]), int(value["denominator"]))
    raise DataUnavailableError(f"Formula contains a non-exact numeric literal: {value!r}")


def evaluate(expression: Any, variables: Mapping[str, Number]) -> Number:
    """Evaluate a deliberately small, exact JSON formula AST.

    Formulae are data, not Python source.  This avoids a parallel set of game
    constants inside application code and preserves the wiki's floor order.
    """
    if isinstance(expression, (int, Fraction)):
        return _number(expression)
    if not isinstance(expression, Mapping):
        raise DataUnavailableError("Formula node must be an object or exact integer")

    op = expression.get("op")
    if op == "const":
        return _number(expression["value"])
    if op == "ref":
        name = str(expression["name"])
        if name not in variables:
            raise DataUnavailableError(f"Formula references missing input {name!r}")
        return _number(variables[name])

    raw_args = expression.get("args", [])
    if op == "if":
        if len(raw_args) != 3:
            raise DataUnavailableError("if requires condition, true branch, and false branch")
        return evaluate(raw_args[1] if evaluate(raw_args[0], variables) else raw_args[2], variables)
    args = [evaluate(argument, variables) for argument in raw_args]
    if op == "add":
        return sum(args, Fraction(0))
    if op == "sub":
        if len(args) != 2:
            raise DataUnavailableError("sub requires exactly two arguments")
        return args[0] - args[1]
    if op == "mul":
        result: Number = 1
        for argument in args:
            result *= argument
        return result
    if op == "div":
        if len(args) != 2 or args[1] == 0:
            raise DataUnavailableError("div requires two arguments and non-zero divisor")
        return Fraction(args[0], args[1])
    if op == "floor":
        if len(args) != 1:
            raise DataUnavailableError("floor requires exactly one argument")
        return args[0] // 1
    if op == "max":
        if not args:
            raise DataUnavailableError("max requires at least one argument")
        return max(args)
    if op == "min":
        if not args:
            raise DataUnavailableError("min requires at least one argument")
        return min(args)
    if op in {"gt", "gte", "lt", "lte", "eq"}:
        if len(args) != 2:
            raise DataUnavailableError(f"{op} requires exactly two arguments")
        return int(
            {
                "gt": args[0] > args[1],
                "gte": args[0] >= args[1],
                "lt": args[0] < args[1],
                "lte": args[0] <= args[1],
                "eq": args[0] == args[1],
            }[op]
        )
    raise DataUnavailableError(f"Unsupported formula operation {op!r}")
