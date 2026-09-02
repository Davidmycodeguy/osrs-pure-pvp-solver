import unittest
from fractions import Fraction

from pure_solver.combat_envelope import (
    AttackOption,
    best_fixed_sequence,
    build_combat_envelope,
    convolve_distributions,
    fixed_option_window_distribution,
    fixed_sequence_window_distribution,
    optimal_ko_probability,
    survival_probability,
)
from pure_solver.evaluation import DamageDistribution


def _option(
    option_id: str,
    probability: dict[int, Fraction],
    *,
    cooldown: int,
    delay: int,
    minimum_distance: int = 1,
    maximum_distance: int = 1,
) -> AttackOption:
    return AttackOption(
        option_id=option_id,
        damage_type="slash",
        cooldown_ticks=cooldown,
        minimum_distance=minimum_distance,
        maximum_distance=maximum_distance,
        impact_delay_by_distance={distance: delay for distance in range(minimum_distance, maximum_distance + 1)},
        distribution=DamageDistribution(probability),
    )


class CombatEnvelopeTests(unittest.TestCase):
    def test_manual_convolution_is_exact(self) -> None:
        left = DamageDistribution({0: Fraction(1, 2), 1: Fraction(1, 2)})
        right = DamageDistribution({0: Fraction(1, 3), 2: Fraction(2, 3)})
        combined = convolve_distributions(left, right)
        self.assertEqual(
            combined.probability,
            {
                0: Fraction(1, 6),
                1: Fraction(1, 6),
                2: Fraction(1, 3),
                3: Fraction(1, 3),
            },
        )

    def test_fixed_option_window_boundaries_match_tick_cutoff(self) -> None:
        option = _option("scim", {0: Fraction(1, 2), 4: Fraction(1, 2)}, cooldown=4, delay=0)
        self.assertEqual(fixed_option_window_distribution(option, tick_window=4, distance=1).attack_count, 1)
        self.assertEqual(fixed_option_window_distribution(option, tick_window=5, distance=1).attack_count, 2)
        self.assertEqual(fixed_option_window_distribution(option, tick_window=8, distance=1).attack_count, 2)
        self.assertEqual(fixed_option_window_distribution(option, tick_window=12, distance=1).attack_count, 3)

    def test_ko_probability_is_monotone_in_tick_window(self) -> None:
        option = _option("club", {0: Fraction(1, 2), 6: Fraction(1, 2)}, cooldown=4, delay=0)
        short = optimal_ko_probability((option,), target_hp=6, tick_window=4, distance=1)
        long = optimal_ko_probability((option,), target_hp=6, tick_window=8, distance=1)
        self.assertLess(short.ko_probability, long.ko_probability)

    def test_burst_vs_speed_choice_changes_with_target(self) -> None:
        fast = _option("fast", {1: Fraction(1)}, cooldown=2, delay=0)
        burst = _option("burst", {0: Fraction(1, 2), 4: Fraction(1, 2)}, cooldown=4, delay=0)
        low_hp = optimal_ko_probability((fast, burst), target_hp=2, tick_window=4, distance=1)
        high_hp = optimal_ko_probability((fast, burst), target_hp=4, tick_window=4, distance=1)
        self.assertEqual(low_hp.first_action, "fast")
        self.assertEqual(high_hp.first_action, "burst")

    def test_delayed_hit_stacking_counts_all_impacts_before_deadline(self) -> None:
        ranged = _option("ranged", {2: Fraction(1)}, cooldown=4, delay=3, minimum_distance=2, maximum_distance=2)
        result = fixed_sequence_window_distribution((ranged, ranged), tick_window=8, distance=2)
        self.assertEqual(result.attack_ticks, (0, 4))
        self.assertEqual(result.impact_ticks, (3, 7))
        self.assertEqual(result.distribution.probability, {4: Fraction(1)})

    def test_no_impact_before_deadline_leaves_zero_damage(self) -> None:
        delayed = _option("slow", {8: Fraction(1)}, cooldown=4, delay=5)
        result = fixed_option_window_distribution(delayed, tick_window=5, distance=1)
        self.assertEqual(result.impact_ticks, ())
        self.assertEqual(result.distribution.probability, {0: Fraction(1)})
        self.assertEqual(result.ko_probability(1), Fraction(0))

    def test_best_fixed_sequence_prefers_deterministic_high_ko_line(self) -> None:
        fast = _option("fast", {1: Fraction(1)}, cooldown=2, delay=0)
        burst = _option("burst", {0: Fraction(1, 2), 4: Fraction(1, 2)}, cooldown=4, delay=0)
        best = best_fixed_sequence((fast, burst), target_hp=4, tick_window=4, distance=1)
        self.assertEqual(best.sequence, ("burst",))
        self.assertEqual(best.ko_probability(4), Fraction(1, 2))

    def test_optimal_ko_is_deterministic_under_ties(self) -> None:
        alpha = _option("alpha", {2: Fraction(1)}, cooldown=4, delay=0)
        beta = _option("beta", {2: Fraction(1)}, cooldown=4, delay=0)
        result = optimal_ko_probability((beta, alpha), target_hp=2, tick_window=4, distance=1)
        self.assertEqual(result.ko_probability, Fraction(1))
        self.assertEqual(result.first_action, "alpha")
        self.assertEqual(result.equally_optimal_first_actions, ("alpha", "beta"))

    def test_projectile_impact_resolves_before_cooldown_ends(self) -> None:
        projectile = _option("projectile", {3: Fraction(1)}, cooldown=4, delay=2)
        result = optimal_ko_probability((projectile,), target_hp=3, tick_window=3, distance=1)
        self.assertEqual(result.ko_probability, Fraction(1))

    def test_materialized_envelope_reports_required_windows_and_ko_thresholds(self) -> None:
        fast = _option("fast", {0: Fraction(1, 2), 2: Fraction(1, 2)}, cooldown=2, delay=0)
        burst = _option("burst", {0: Fraction(1, 2), 5: Fraction(1, 2)}, cooldown=4, delay=0)

        envelope = build_combat_envelope(
            "candidate",
            "medium-defence",
            (burst, fast),
            hitpoints=20,
            prayer=13,
            distance=1,
        )
        document = envelope.to_document()

        self.assertEqual(document["windows"], (4, 5, 8, 12))
        self.assertEqual(document["hp_thresholds"], (5, 10, 15, 20, 25, 30))
        self.assertEqual(len(document["stack_ko"]), 24)
        self.assertIn("ko:4:5", envelope.normalized_metrics)
        self.assertTrue(envelope.equivalence_signature)
        self.assertEqual(
            survival_probability(DamageDistribution({0: Fraction(1, 4), 20: Fraction(3, 4)}), 20), Fraction(1, 4)
        )

    def test_envelope_uses_only_actions_legal_at_the_declared_distance(self) -> None:
        melee = _option("melee", {2: Fraction(1)}, cooldown=4, delay=0, minimum_distance=1, maximum_distance=1)
        ranged = _option("ranged", {1: Fraction(1)}, cooldown=3, delay=1, minimum_distance=2, maximum_distance=2)

        envelope = build_combat_envelope(
            "candidate",
            "distance-two",
            (melee, ranged),
            hitpoints=10,
            prayer=1,
            distance=2,
            windows=(4,),
            hp_thresholds=(5,),
        )

        self.assertEqual([option.option_id for option in envelope.options], ["ranged"])
        self.assertIn("range:legal:2", envelope.capabilities)
        self.assertNotIn("range:legal:1", envelope.capabilities)

    def test_duplicate_option_ids_are_rejected(self) -> None:
        alpha = _option("dup", {2: Fraction(1)}, cooldown=4, delay=0)
        beta = _option("dup", {3: Fraction(1)}, cooldown=4, delay=0)
        with self.assertRaisesRegex(ValueError, "unique"):
            best_fixed_sequence((alpha, beta), target_hp=2, tick_window=4, distance=1)
        with self.assertRaisesRegex(ValueError, "unique"):
            optimal_ko_probability((alpha, beta), target_hp=2, tick_window=4, distance=1)
