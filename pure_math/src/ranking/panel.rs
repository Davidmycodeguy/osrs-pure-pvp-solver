//! Simulator seed panel selection (`survivor_ranking._select_panel`): forced
//! extremes, damage/weapon-type representatives, then integer-midrank
//! farthest-point sampling.

use std::collections::BTreeMap;

use super::scores::midrank_integers;
use super::{RankingCandidate, DAMAGE_TYPES};
use crate::rational::Rational;

pub struct PanelSelection {
    /// Candidate indices in selection order.
    pub selected: Vec<usize>,
    pub reasons: BTreeMap<String, Vec<String>>,
}

/// `min(candidates, key=(-score, candidate_id))`: candidates are id-sorted, so the
/// first strict maximum wins ties.
fn best_candidate(candidates: &[RankingCandidate], eligible: &[usize], score: impl Fn(&RankingCandidate) -> Rational) -> usize {
    let mut best: Option<(usize, Rational)> = None;
    for &index in eligible {
        let value = score(&candidates[index]);
        if best.as_ref().is_none_or(|(_, current)| value > *current) {
            best = Some((index, value));
        }
    }
    best.expect("non-empty eligible set").0
}

fn panel_features(candidate: &RankingCandidate) -> Vec<Rational> {
    let mut features: Vec<Rational> = candidate.sustained_dpt.to_vec();
    features.extend(candidate.ko_by_window.iter().cloned());
    features.extend([
        Rational::from(candidate.max_hit),
        Rational::from(candidate.potted_max_hit),
        Rational::from(candidate.maximum_range),
        candidate.physical_defence_average.clone(),
        Rational::from(candidate.magic_attack_bonus),
        Rational::from(candidate.magic_defence_bonus),
        Rational::from(candidate.prayer_bonus),
    ]);
    features
}

/// Scores one candidate on a forced-extreme axis.
type ExtremeScore = fn(&RankingCandidate) -> Rational;

fn forced_extremes() -> Vec<(&'static str, ExtremeScore)> {
    vec![
        ("sustain_average_extreme", |c| c.sustain_average.clone()),
        ("sustain_worst_extreme", |c| c.sustain_worst.clone()),
        ("four_tick_ko_extreme", |c| c.ko_by_window[0].clone()),
        ("twelve_tick_ko_extreme", |c| c.ko_by_window[3].clone()),
        ("potted_max_hit_extreme", |c| Rational::from(c.potted_max_hit)),
        ("physical_defence_extreme", |c| c.physical_defence_average.clone()),
        ("magic_defence_extreme", |c| Rational::from(c.magic_defence_bonus)),
        ("magic_attack_gear_extreme", |c| Rational::from(c.magic_attack_bonus)),
        ("range_extreme", |c| Rational::from(c.maximum_range)),
        ("prayer_bonus_extreme", |c| Rational::from(c.prayer_bonus)),
    ]
}

/// Exact integer midranks on a shared 0..2(N-1) scale, one vector per candidate.
fn rank_vectors(candidates: &[RankingCandidate]) -> Vec<Vec<i64>> {
    let features: Vec<Vec<Rational>> = candidates.iter().map(panel_features).collect();
    let dimensions = features[0].len();
    let mut vectors = vec![vec![0i64; dimensions]; candidates.len()];
    for dimension in 0..dimensions {
        let column: Vec<Rational> = features.iter().map(|row| row[dimension].clone()).collect();
        for (index, midrank) in midrank_integers(&column).into_iter().enumerate() {
            vectors[index][dimension] = midrank;
        }
    }
    vectors
}

fn distance(vectors: &[Vec<i64>], left: usize, right: usize) -> i64 {
    vectors[left].iter().zip(&vectors[right]).map(|(a, b)| (a - b) * (a - b)).sum()
}

pub fn select_panel(candidates: &[RankingCandidate], requested_size: usize) -> PanelSelection {
    assert!(requested_size >= 1, "panel_size must be positive");
    let requested_size = requested_size.min(candidates.len());
    let mut selected: Vec<usize> = Vec::new();
    let mut reasons: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut add = |index: usize, reason: String| {
        let id = &candidates[index].candidate_id;
        if let Some(existing) = reasons.get_mut(id) {
            existing.push(reason);
        } else if selected.len() < requested_size {
            selected.push(index);
            reasons.insert(id.clone(), vec![reason]);
        }
    };
    let everyone: Vec<usize> = (0..candidates.len()).collect();
    for (reason, score) in forced_extremes() {
        add(best_candidate(candidates, &everyone, score), reason.to_owned());
    }
    // One strong representative per damage type keeps ranged and crush/stab
    // counters in the seed set even when melee dominates the population.
    for damage_type in DAMAGE_TYPES {
        let eligible: Vec<usize> = everyone
            .iter()
            .copied()
            .filter(|&i| candidates[i].damage_types.iter().any(|d| d == damage_type))
            .collect();
        if !eligible.is_empty() {
            add(
                best_candidate(candidates, &eligible, |c| c.sustain_average.clone()),
                format!("damage_type_representative:{damage_type}"),
            );
        }
    }
    let mut weapon_types: Vec<&str> = candidates.iter().map(|c| c.weapon_type.as_str()).collect();
    weapon_types.sort_unstable();
    weapon_types.dedup();
    for weapon_type in weapon_types {
        let eligible: Vec<usize> = everyone.iter().copied().filter(|&i| candidates[i].weapon_type == weapon_type).collect();
        add(
            best_candidate(candidates, &eligible, |c| c.sustain_average.clone()),
            format!("weapon_type_representative:{weapon_type}"),
        );
    }

    let vectors = rank_vectors(candidates);
    let mut minimum_distance: Vec<i64> = if selected.is_empty() {
        vec![0; candidates.len()]
    } else {
        (0..candidates.len())
            .map(|index| selected.iter().map(|&s| distance(&vectors, index, s)).min().expect("non-empty"))
            .collect()
    };
    let mut is_selected = vec![false; candidates.len()];
    for &index in &selected {
        is_selected[index] = true;
    }
    while selected.len() < requested_size {
        let remaining: Vec<usize> = (0..candidates.len()).filter(|&i| !is_selected[i]).collect();
        // min by (-minimum_distance, -sustain_average, candidate_id): id order is index order.
        let mut next = remaining[0];
        for &index in &remaining[1..] {
            let (distance_now, distance_best) = (minimum_distance[index], minimum_distance[next]);
            if distance_now > distance_best || (distance_now == distance_best && candidates[index].sustain_average > candidates[next].sustain_average) {
                next = index;
            }
        }
        selected.push(next);
        reasons.insert(candidates[next].candidate_id.clone(), vec!["envelope_farthest_point".to_owned()]);
        is_selected[next] = true;
        for &index in &remaining {
            minimum_distance[index] = minimum_distance[index].min(distance(&vectors, index, next));
        }
    }
    PanelSelection { selected, reasons }
}
