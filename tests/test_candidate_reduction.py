import unittest
from fractions import Fraction

from pure_solver.candidate_reduction import (
    ReductionCandidate,
    candidate_from_combat_envelopes,
    deduplicate_candidates,
    pareto_prune_candidates,
    reduce_candidates,
    select_diverse_seeds,
)
from pure_solver.combat_envelope import AttackOption, build_combat_envelope
from pure_solver.evaluation import DamageDistribution


def _candidate(
    candidate_id: str,
    *,
    signature: object | None = None,
    comparison_class: object = "default",
    capabilities: tuple[str, ...] = (),
    **metrics: int | float | Fraction,
) -> ReductionCandidate:
    return ReductionCandidate(
        candidate_id,
        equivalence_signature=signature if signature is not None else candidate_id,
        comparison_class=comparison_class,
        normalized_metrics=metrics,
        capabilities=capabilities,
    )


class CandidateReductionTests(unittest.TestCase):
    def test_exact_combat_envelopes_feed_reduction_metrics(self) -> None:
        option = AttackOption(
            option_id="scimitar",
            damage_type="slash",
            cooldown_ticks=4,
            minimum_distance=1,
            maximum_distance=1,
            impact_delay_by_distance={1: 0},
            distribution=DamageDistribution({0: Fraction(1, 2), 4: Fraction(1, 2)}),
        )
        low = build_combat_envelope(
            "build",
            "low",
            (option,),
            hitpoints=20,
            prayer=1,
            distance=1,
            windows=(4,),
            hp_thresholds=(5,),
        )
        high = build_combat_envelope(
            "build",
            "high",
            (option,),
            hitpoints=20,
            prayer=1,
            distance=1,
            windows=(4,),
            hp_thresholds=(5,),
        )

        candidate = candidate_from_combat_envelopes(
            "build",
            (high, low),
            comparison_class={"inventory_slots": 28},
            additional_metrics={"survival:melee": Fraction(3, 4)},
        )

        self.assertIn("low:ko:4:5", candidate.metric_map)
        self.assertIn("high:expected:scimitar:4", candidate.metric_map)
        self.assertEqual(candidate.metric_map["survival:melee"], Fraction(3, 4))

    def test_exact_duplicate_dedupe_keeps_deterministic_canonical_survivor(self) -> None:
        duplicate_a = _candidate(
            "build-a",
            signature={"kit": "rscim", "style": "slash"},
            dps=Fraction(13, 10),
            ko_20=Fraction(2, 5),
        )
        duplicate_b = _candidate(
            "build-b",
            signature={"style": "slash", "kit": "rscim"},
            dps=Fraction(13, 10),
            ko_20=Fraction(2, 5),
        )
        survivors, audits = deduplicate_candidates((duplicate_b, duplicate_a))
        self.assertEqual([candidate.candidate_id for candidate in survivors], ["build-a"])
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].removed_candidate_id, "build-b")
        self.assertEqual(audits[0].surviving_candidate_id, "build-a")

    def test_same_dps_candidates_with_different_ko_windows_are_preserved(self) -> None:
        fast_ko = _candidate(
            "fast-ko",
            comparison_class="melee",
            dps=Fraction(5, 4),
            ko_5=Fraction(7, 10),
            ko_20=Fraction(1, 4),
        )
        deep_ko = _candidate(
            "deep-ko",
            comparison_class="melee",
            dps=Fraction(5, 4),
            ko_5=Fraction(3, 5),
            ko_20=Fraction(2, 5),
        )
        survivors, audits = pareto_prune_candidates((fast_ko, deep_ko))
        self.assertEqual({candidate.candidate_id for candidate in survivors}, {"fast-ko", "deep-ko"})
        self.assertEqual(audits, ())

    def test_incomplete_equivalence_signature_cannot_hide_metric_or_capability_difference(self) -> None:
        baseline = _candidate(
            "baseline",
            signature="accidentally-coarse",
            comparison_class="melee",
            capabilities=("style:melee",),
            dps=1,
            ko=1,
        )
        specialist = _candidate(
            "specialist",
            signature="accidentally-coarse",
            comparison_class="melee",
            capabilities=("style:melee", "switch:2h"),
            dps=1,
            ko=2,
        )

        survivors, audits = deduplicate_candidates((baseline, specialist))

        self.assertEqual({candidate.candidate_id for candidate in survivors}, {"baseline", "specialist"})
        self.assertEqual(audits, ())

    def test_style_and_range_niches_block_dominance(self) -> None:
        melee_tank = _candidate(
            "melee-tank",
            comparison_class="hybrid",
            capabilities=("style:melee", "range:1"),
            dps=Fraction(6, 5),
            defence_melee=8,
            defence_ranged=4,
        )
        ranger = _candidate(
            "ranger",
            comparison_class="hybrid",
            capabilities=("style:ranged", "range:7"),
            dps=Fraction(6, 5),
            defence_melee=7,
            defence_ranged=5,
        )
        result = reduce_candidates((melee_tank, ranger))
        self.assertEqual({candidate.candidate_id for candidate in result.retained_candidates}, {"melee-tank", "ranger"})
        niche_ids = {niche.representative_candidate_id for niche in result.preserved_capability_niches}
        self.assertIn("melee-tank", niche_ids)
        self.assertIn("ranger", niche_ids)

    def test_strict_dominance_prunes_only_same_metric_dimension_group(self) -> None:
        superior = _candidate(
            "superior",
            comparison_class="melee",
            capabilities=("style:melee", "range:1"),
            dps=Fraction(7, 5),
            ko_20=Fraction(9, 20),
            defence_melee=8,
        )
        inferior = _candidate(
            "inferior",
            comparison_class="melee",
            capabilities=("style:melee",),
            dps=Fraction(6, 5),
            ko_20=Fraction(7, 20),
            defence_melee=6,
        )
        different_dimensions = _candidate(
            "different-dimensions",
            comparison_class="melee",
            dps=Fraction(1, 1),
            ko_12=Fraction(1, 2),
        )
        survivors, audits = pareto_prune_candidates((inferior, different_dimensions, superior))
        self.assertEqual({candidate.candidate_id for candidate in survivors}, {"superior", "different-dimensions"})
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].removed_candidate_id, "inferior")
        self.assertEqual(audits[0].surviving_candidate_id, "superior")

    def test_reduction_counts_and_audits_are_deterministic(self) -> None:
        candidates = (
            _candidate("c3", signature="same", comparison_class="melee", capabilities=("range:7",), dps=1, ko=1),
            _candidate("c1", signature="same", comparison_class="melee", capabilities=("range:7",), dps=1, ko=1),
            _candidate("c4", comparison_class="melee", capabilities=("style:melee",), dps=3, ko=3),
            _candidate("c2", comparison_class="melee", capabilities=("style:melee",), dps=2, ko=2),
        )
        forward = reduce_candidates(candidates)
        backward = reduce_candidates(tuple(reversed(candidates)))
        self.assertEqual(forward.to_document(), backward.to_document())
        self.assertEqual(forward.counts.starting_candidates, 4)
        self.assertEqual(forward.counts.exact_duplicates_removed, 1)
        self.assertEqual(forward.counts.dominated_candidates_removed, 1)
        self.assertEqual(forward.counts.remaining_pareto_candidates, 2)

    def test_seed_selection_keeps_metric_extremes_and_capability_representatives(self) -> None:
        candidates = (
            _candidate("sustained", comparison_class="all", capabilities=("style:melee",), dps=10, ko=4, tank=5),
            _candidate(
                "burst", comparison_class="all", capabilities=("style:melee", "switch:2h"), dps=8, ko=10, tank=4
            ),
            _candidate(
                "tank", comparison_class="all", capabilities=("style:melee", "defence:melee"), dps=7, ko=5, tank=10
            ),
            _candidate("mage", comparison_class="all", capabilities=("style:magic", "range:8"), dps=6, ko=8, tank=3),
            _candidate("archer", comparison_class="all", capabilities=("style:ranged", "range:7"), dps=9, ko=6, tank=2),
        )
        seeds = select_diverse_seeds(candidates, 4)
        selected_ids = [candidate.candidate_id for candidate in seeds.selected_candidates]
        self.assertEqual(len(selected_ids), len(set(selected_ids)))
        self.assertIn("sustained", selected_ids)
        self.assertIn("burst", selected_ids)
        self.assertIn("tank", selected_ids)
        self.assertIn("mage", selected_ids)
        reasons = {record.candidate_id: set(record.reasons) for record in seeds.reasons}
        self.assertIn("metric_extreme:dps", reasons["sustained"])
        self.assertIn("metric_extreme:ko", reasons["burst"])
        self.assertIn("metric_extreme:tank", reasons["tank"])

    def test_seed_selection_uses_farthest_point_after_forced_extremes(self) -> None:
        candidates = (
            _candidate("alpha", comparison_class="all", dps=10, ko=1, tank=1),
            _candidate("beta", comparison_class="all", dps=1, ko=10, tank=1),
            _candidate("gamma", comparison_class="all", dps=1, ko=1, tank=10),
            _candidate("delta", comparison_class="all", dps=6, ko=6, tank=6),
        )
        seeds = select_diverse_seeds(candidates, 4)
        selected_ids = [candidate.candidate_id for candidate in seeds.selected_candidates]
        self.assertEqual(selected_ids[-1], "delta")
        self.assertIn("coverage_farthest_point", set(seeds.reasons[-1].reasons))


if __name__ == "__main__":
    unittest.main()
