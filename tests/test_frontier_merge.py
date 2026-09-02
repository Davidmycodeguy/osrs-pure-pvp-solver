import unittest

from pure_solver.errors import MechanicConflictError
from pure_solver.frontier_merge import merge_offense_frontiers


def _candidate(name: str, dpt: int, ko: int) -> dict:
    return {
        "name": name,
        "primary": {"expected_damage_per_tick": {"numerator": dpt, "denominator": 1}, "max_hit": dpt},
        "ko": {"expected_damage_per_tick": {"numerator": 1, "denominator": 1}, "max_hit": ko},
        "inventory_frontier": {
            "best_total_healing": {"total_healing": 10},
            "best_total_actions": {"total_actions": 10},
        },
    }


def _document(combat: int, candidate: dict) -> dict:
    return {
        "scope": "fixture",
        "account_mode": "independent_hp",
        "verification": {},
        "reproducibility": {"hash": "same"},
        "target": {},
        "assumptions": [],
        "search": {
            "generated_accounts": 2,
            "pareto_accounts": 1,
            "dominated_accounts_pruned": 1,
            "evaluated_candidates": 1,
            "prayer_levels_considered": [1],
        },
        "top_overall": [candidate],
        "top_by_ko_max_hit": [candidate],
        "best_by_hitpoints": {"40": candidate},
        "best_by_combat_level": {str(combat): candidate},
    }


class FrontierMergeTests(unittest.TestCase):
    def test_merge_ranks_and_sums_shards(self) -> None:
        merged = merge_offense_frontiers(
            (
                _document(30, _candidate("a", 2, 5)),
                _document(31, _candidate("b", 3, 4)),
            ),
            top=1,
        )
        self.assertEqual(merged["top_overall"][0]["name"], "b")
        self.assertEqual(merged["top_by_ko_max_hit"][0]["name"], "a")
        self.assertEqual(merged["search"]["generated_accounts"], 4)
        self.assertEqual(merged["search"]["shard_count"], 2)

    def test_merge_rejects_mixed_rulesets(self) -> None:
        left = _document(30, _candidate("a", 2, 5))
        right = _document(31, _candidate("b", 3, 4))
        right["reproducibility"] = {"hash": "different"}
        with self.assertRaises(MechanicConflictError):
            merge_offense_frontiers((left, right))
