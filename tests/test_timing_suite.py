import unittest

from pure_solver.errors import MechanicConflictError
from pure_solver.experiments import derive_timing_suite_claim


def _suite() -> dict[str, object]:
    pipeline = ["receive_inputs", "apply_actions", "schedule_hits", "resolve_hits", "check_death"]
    return {
        "experiment_id": "fixture-suite",
        "game_version": "fixture",
        "evidence_manifest": "fixture-manifest",
        "tick_pipeline_samples": [pipeline] * 20,
        "same_tick_ko_samples": [
            {"priority": priority, "outcome": outcome, "evidence_ref": f"{priority}-{index}"}
            for priority, outcome in (("player", "player_win"), ("opponent", "opponent_win"))
            for index in range(20)
        ],
        "impact_samples": [
            {
                "kind": kind,
                "distance_tiles": distance,
                "attack_tick": 10,
                "impact_tick": 10 + delay,
                "evidence_ref": f"{kind}-{index}",
            }
            for kind, distance, delay in (("melee", 1, 0), ("ranged", 2, 3), ("magic", 7, 2))
            for index in range(20)
        ],
    }


class TimingSuiteTests(unittest.TestCase):
    def test_complete_consensus_emits_all_five_experimental_mechanics(self) -> None:
        claim = derive_timing_suite_claim(_suite())
        self.assertEqual(len(claim.mechanic_documents()), 5)
        self.assertEqual(claim.impact_delay_by_kind_and_distance["ranged"], {2: 3})
        self.assertEqual(claim.status, "experimental")

    def test_conflicting_impact_is_rejected(self) -> None:
        document = _suite()
        document["impact_samples"][-1]["impact_tick"] = 14
        with self.assertRaises(MechanicConflictError):
            derive_timing_suite_claim(document)
