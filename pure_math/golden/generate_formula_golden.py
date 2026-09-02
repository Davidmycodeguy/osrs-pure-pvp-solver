"""Emit golden cases for the Rust formula evaluator.

Every formula mechanic in the ruleset is evaluated by the Python reference
(`pure_solver.formula.evaluate`) over deterministic sampled inputs.  The Rust
port must reproduce each result exactly (numerator and denominator).

Run from the repository root:
    $env:PYTHONPATH='src'; python pure_math/golden/generate_formula_golden.py
"""
from __future__ import annotations

import json
import random
import sys
from fractions import Fraction
from pathlib import Path

from pure_solver.formula import evaluate

ROOT = Path(__file__).resolve().parents[2]
RULESET = ROOT / "rulesets" / "osrs-f2p-v1"
OUTPUT = ROOT / "pure_math" / "tests" / "fixtures" / "formula-golden.json"
CASES_PER_MECHANIC = 40
SEED = 30

MULTIPLIER_CHOICES = (
    Fraction(1), Fraction(21, 20), Fraction(11, 10), Fraction(23, 20), Fraction(6, 5), Fraction(1, 2),
)
LEVEL_RANGE = (1, 99)
BONUS_RANGE = (-20, 120)
BOOST_RANGE = (0, 15)
ROLL_RANGE = (0, 20_000)


def referenced_names(node: object) -> set[str]:
    if isinstance(node, dict):
        names = {str(node["name"])} if node.get("op") == "ref" else set()
        return names.union(*(referenced_names(value) for value in node.values()))
    if isinstance(node, list):
        return set().union(*(referenced_names(value) for value in node))
    return set()


def sample_value(name: str, rng: random.Random) -> Fraction:
    if name.endswith("_multiplier"):
        return rng.choice(MULTIPLIER_CHOICES)
    if name.endswith("_roll"):
        return Fraction(rng.randint(*ROLL_RANGE))
    if name.endswith("_boost") or name == "style_bonus":
        return Fraction(rng.randint(*BOOST_RANGE))
    if name.endswith("_bonus") or name.endswith("_percent"):
        return Fraction(rng.randint(*BONUS_RANGE))
    if name.startswith("effective_") or name.startswith("base_") or name == "spell_base_max_hit":
        return Fraction(rng.randint(1, 200))
    return Fraction(rng.randint(*LEVEL_RANGE))


def encode(value: Fraction | int) -> dict[str, int]:
    fraction = Fraction(value)
    return {"numerator": fraction.numerator, "denominator": fraction.denominator}


def golden_cases() -> list[dict]:
    mechanics = json.loads((RULESET / "mechanics.json").read_text(encoding="utf-8"))["mechanics"]
    rng = random.Random(SEED)
    cases = []
    for mechanic in mechanics:
        formula = mechanic.get("value")
        if not (isinstance(formula, dict) and "op" in formula):
            continue
        names = sorted(referenced_names(formula))
        for _ in range(CASES_PER_MECHANIC):
            variables = {name: sample_value(name, rng) for name in names}
            try:
                result = evaluate(formula, variables)
            except Exception as error:  # recorded as an expected failure
                cases.append(
                    {
                        "mechanic_id": mechanic["mechanic_id"],
                        "variables": {k: encode(v) for k, v in variables.items()},
                        "error": type(error).__name__,
                    }
                )
                continue
            cases.append({
                "mechanic_id": mechanic["mechanic_id"],
                "variables": {k: encode(v) for k, v in variables.items()},
                "result": encode(result),
            })
    return cases


def main() -> int:
    cases = golden_cases()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"seed": SEED, "cases": cases}, indent=1, sort_keys=True), encoding="utf-8")
    print(f"wrote {len(cases)} cases to {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
