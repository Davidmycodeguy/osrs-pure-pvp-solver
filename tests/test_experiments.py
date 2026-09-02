import unittest

from pure_solver.errors import DataUnavailableError, MechanicConflictError
from pure_solver.experiments import derive_range_to_melee_claim


def _document(delays: list[int]) -> dict[str, object]:
    return {
        "experiment_id": "range-stack-test",
        "game_version": "test",
        "date": "2026-09-01",
        "world": "test-world",
        "conditions": "stationary synthetic fixture",
        "inputs": "ranged, switch, melee",
        "expected_outcome": "derive timing",
        "observed_outcome": "fixture",
        "conclusion": "fixture only",
        "observations": [
            {
                "sample_id": f"sample-{index}",
                "distance_tiles": 2,
                "ranged_attack_tick": 0,
                "ranged_impact_tick": delay,
                "weapon_switch_tick": 3,
                "melee_attack_tick": 3,
                "melee_impact_tick": 3,
                "evidence_ref": f"fixture-{index}",
            }
            for index, delay in enumerate(delays)
        ],
    }


class ExperimentValidationTests(unittest.TestCase):
    def test_repeated_agreeing_samples_produce_experimental_claim(self) -> None:
        claim = derive_range_to_melee_claim(_document([3] * 20))
        self.assertEqual(claim.ranged_impact_delay_by_distance, {2: 3})
        self.assertEqual(claim.melee_impact_delay, 0)
        self.assertTrue(claim.switch_and_attack_same_tick)
        self.assertEqual(claim.status, "experimental")

    def test_conflicting_samples_are_not_averaged(self) -> None:
        with self.assertRaises(MechanicConflictError):
            derive_range_to_melee_claim(_document([3] * 19 + [4]))

    def test_insufficient_samples_do_not_promote(self) -> None:
        with self.assertRaises(DataUnavailableError):
            derive_range_to_melee_claim(_document([3] * 19))
