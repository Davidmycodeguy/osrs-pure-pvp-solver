import random
import unittest

from pure_solver.latency import InputTimingProfile, LatencyMode, accept_input


class LatencyTests(unittest.TestCase):
    def test_perfect_and_deterministic_acceptance_are_separate(self) -> None:
        perfect = InputTimingProfile(LatencyMode.PERFECT, 600, 0, source_ids=("fixture",), status="verified")
        self.assertEqual(accept_input(perfect, generated_tick=4, generated_offset_ms=0).accepted_tick, 4)
        deterministic = InputTimingProfile(
            LatencyMode.DETERMINISTIC,
            600,
            ping_ms=100,
            client_delay_ms=20,
            server_delay_ms=30,
            source_ids=("fixture",),
            status="verified",
        )
        accepted = accept_input(deterministic, generated_tick=4, generated_offset_ms=500)
        self.assertEqual(accepted.accepted_tick, 6)

    def test_empirical_profile_requires_explicit_experimental_permission(self) -> None:
        profile = InputTimingProfile(
            LatencyMode.EMPIRICAL,
            600,
            ping_samples_ms=(50, 80),
            input_offsets_ms=(100, 500),
            source_ids=("histogram-fixture",),
            status="experimental",
        )
        with self.assertRaises(Exception):
            accept_input(profile, generated_tick=0, generated_offset_ms=0)
        result = accept_input(
            profile,
            generated_tick=0,
            generated_offset_ms=0,
            rng=random.Random(1),
            allow_experimental=True,
        )
        self.assertGreaterEqual(result.accepted_tick, 1)
