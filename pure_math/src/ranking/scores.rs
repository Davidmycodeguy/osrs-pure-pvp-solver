//! Population midrank percentiles, category composites, niche flags and the
//! top-level `rank_survivor_manifest` orchestration.

use std::cmp::Ordering;
use std::collections::{BTreeMap, HashSet};
use std::path::Path;

use anyhow::{bail, Result};
use rayon::prelude::*;

use super::load::load_ranking_candidates;
use super::panel::select_panel;
use super::race::{race_scenarios, RaceConfig};
use super::{RaceScenario, RankedCandidate, RankingCandidate, RankingConfig, SurvivorRankingReport, DAMAGE_TYPES, DEFENCE_STATES, WINDOWS};
use crate::combat::CombatKernel;
use crate::rational::Rational;

pub const CATEGORIES: [&str; 5] = ["sustain", "race", "burst", "defence", "utility"];

/// `bisect_left + bisect_right - 1` for every value against the sorted population.
pub fn midrank_integers(values: &[Rational]) -> Vec<i64> {
    let mut order: Vec<usize> = (0..values.len()).collect();
    order.par_sort_by(|&a, &b| values[a].cmp(&values[b]));
    let mut midranks = vec![0i64; values.len()];
    let mut start = 0;
    while start < order.len() {
        let mut end = start + 1;
        while end < order.len() && values[order[end]] == values[order[start]] {
            end += 1;
        }
        let midrank = (start + end) as i64 - 1;
        for &index in &order[start..end] {
            midranks[index] = midrank;
        }
        start = end;
    }
    midranks
}

pub fn midrank_percentiles(values: &[Rational]) -> Vec<Rational> {
    if values.len() == 1 {
        return vec![Rational::one()];
    }
    let denominator = 2 * (values.len() as i128 - 1);
    midrank_integers(values)
        .into_iter()
        .map(|midrank| Rational::new(midrank as i128, denominator))
        .collect()
}

fn penalty_indices(first: &[RaceScenario]) -> (usize, usize) {
    let position = |penalty: i64| first.iter().position(|s| s.eat_penalty == penalty);
    let primary = position(3).unwrap_or(0);
    (primary, position(0).unwrap_or(primary))
}

fn column(candidates: &[RankingCandidate], value: impl Fn(&RankingCandidate) -> Rational + Sync + Send) -> Vec<Rational> {
    candidates.par_iter().map(value).collect()
}

fn metric_groups(candidates: &[RankingCandidate], races: &[Vec<RaceScenario>]) -> Vec<(&'static str, Vec<Rational>)> {
    let (primary, sensitivity) = penalty_indices(&races[0]);
    let mut groups: Vec<(&'static str, Vec<Rational>)> = Vec::new();
    for index in 0..DEFENCE_STATES.len() {
        groups.push(("sustain", column(candidates, |c| c.sustained_dpt[index].clone())));
    }
    groups.push((
        "race",
        races
            .par_iter()
            .map(|item| item.iter().map(|s| s.worst_margin_fish.clone()).min().expect("non-empty"))
            .collect(),
    ));
    groups.push((
        "race",
        races.par_iter().map(|item| item[primary].tenth_percentile_margin_fish.clone()).collect(),
    ));
    groups.push(("race", races.par_iter().map(|item| item[primary].mean_margin_fish.clone()).collect()));
    groups.push(("race", races.par_iter().map(|item| item[sensitivity].mean_margin_fish.clone()).collect()));
    for index in 0..WINDOWS.len() {
        groups.push(("burst", column(candidates, |c| c.ko_by_window[index].clone())));
    }
    groups.push(("burst", column(candidates, |c| Rational::from(c.max_hit))));
    groups.push(("burst", column(candidates, |c| Rational::from(c.potted_max_hit))));
    for index in 0..DAMAGE_TYPES.len() {
        groups.push(("defence", column(candidates, |c| Rational::from(c.defence_rolls[index]))));
    }
    groups.push(("defence", column(candidates, |c| Rational::from(c.magic_defence_bonus))));
    groups.push(("utility", column(candidates, |c| Rational::from(c.maximum_range))));
    groups.push(("utility", column(candidates, |c| Rational::from(c.styles.len() as i64))));
    groups.push(("utility", column(candidates, |c| Rational::from(c.prayer_level()))));
    groups.push(("utility", column(candidates, |c| Rational::from(c.prayer_bonus))));
    groups.push(("utility", column(candidates, |c| Rational::from(c.magic_attack_bonus))));
    groups
}

/// Equal-weight mean percentile per category, one map per candidate.
pub fn category_scores(candidates: &[RankingCandidate], races: &[Vec<RaceScenario>]) -> Vec<BTreeMap<&'static str, Rational>> {
    let groups = metric_groups(candidates, races);
    let percentiles: Vec<(&'static str, Vec<Rational>)> = groups.par_iter().map(|(category, values)| (*category, midrank_percentiles(values))).collect();
    let metric_counts: BTreeMap<&str, i64> = CATEGORIES
        .iter()
        .map(|c| (*c, percentiles.iter().filter(|(cat, _)| cat == c).count() as i64))
        .collect();
    (0..candidates.len())
        .into_par_iter()
        .map(|index| {
            CATEGORIES
                .iter()
                .map(|category| {
                    let total = percentiles
                        .iter()
                        .filter(|(cat, _)| cat == category)
                        .fold(Rational::zero(), |acc, (_, values)| acc + &values[index]);
                    (*category, total / Rational::from(metric_counts[category]))
                })
                .collect()
        })
        .collect()
}

/// Top-1% niche flags plus damage-type representative panel reasons, sorted.
pub fn extreme_flags(candidates: &[RankingCandidate], panel_reasons: &BTreeMap<String, Vec<String>>) -> Vec<Vec<String>> {
    let metrics: Vec<(&str, Vec<Rational>)> = vec![
        ("sustain_extreme", column(candidates, |c| c.sustain_worst.clone())),
        ("four_tick_ko_extreme", column(candidates, |c| c.ko_by_window[0].clone())),
        ("twelve_tick_ko_extreme", column(candidates, |c| c.ko_by_window[3].clone())),
        ("potted_max_hit_extreme", column(candidates, |c| Rational::from(c.potted_max_hit))),
        ("physical_defence_extreme", column(candidates, |c| c.physical_defence_average.clone())),
        ("magic_defence_extreme", column(candidates, |c| Rational::from(c.magic_defence_bonus))),
        ("magic_attack_gear_extreme", column(candidates, |c| Rational::from(c.magic_attack_bonus))),
        ("range_extreme", column(candidates, |c| Rational::from(c.maximum_range))),
    ];
    let percentile_rows: Vec<(&str, Vec<Rational>)> = metrics.par_iter().map(|(name, values)| (*name, midrank_percentiles(values))).collect();
    let threshold = Rational::new(99, 100);
    candidates
        .iter()
        .enumerate()
        .map(|(index, candidate)| {
            let mut current: HashSet<String> = percentile_rows
                .iter()
                .filter(|(_, p)| p[index] >= threshold)
                .map(|(name, _)| name.to_string())
                .collect();
            if let Some(reasons) = panel_reasons.get(&candidate.candidate_id) {
                current.extend(reasons.iter().filter(|r| r.starts_with("damage_type_representative:")).cloned());
            }
            let mut flags: Vec<String> = current.into_iter().collect();
            flags.sort();
            flags
        })
        .collect()
}

/// Deduplicated, non-negative penalties that include the 3-tick primary and 0-tick sensitivity cases.
pub fn validate_eat_penalties(values: &[i64]) -> Result<Vec<i64>> {
    let mut penalties: Vec<i64> = Vec::new();
    for &value in values {
        if !penalties.contains(&value) {
            penalties.push(value);
        }
    }
    if penalties.is_empty() || penalties.iter().any(|v| *v < 0) {
        bail!("eat_penalties must contain non-negative integers");
    }
    if !penalties.contains(&0) || !penalties.contains(&3) {
        bail!("eat_penalties must include the primary 3-tick and 0-tick sensitivity cases");
    }
    Ok(penalties)
}

fn validated_penalties(config: &RankingConfig) -> Result<Vec<i64>> {
    validate_eat_penalties(&config.eat_penalties)
}

pub fn tier_for(rank: usize, count: usize, niche: bool) -> &'static str {
    let s_cutoff = count.div_ceil(100).max(1);
    let a_cutoff = count.div_ceil(20).max(s_cutoff);
    let b_cutoff = count.div_ceil(5).max(a_cutoff);
    if rank <= s_cutoff {
        "S"
    } else if rank <= a_cutoff {
        "A"
    } else if rank <= b_cutoff {
        "B"
    } else if niche {
        "N"
    } else {
        "C"
    }
}

fn ranking_order(candidates: &[RankingCandidate], overall: &[Rational], scores: &[BTreeMap<&'static str, Rational>]) -> Vec<usize> {
    let mut order: Vec<usize> = (0..candidates.len()).collect();
    let tie_break = ["race", "burst", "sustain", "defence", "utility"];
    order.par_sort_by(|&a, &b| {
        overall[b]
            .cmp(&overall[a])
            .then_with(|| {
                tie_break
                    .iter()
                    .map(|key| scores[b][key].cmp(&scores[a][key]))
                    .find(|o| *o != Ordering::Equal)
                    .unwrap_or(Ordering::Equal)
            })
            .then_with(|| candidates[a].candidate_id.cmp(&candidates[b].candidate_id))
    });
    order
}

/// Rank every resolved survivor without deleting any candidate.
pub fn rank_survivor_manifest(path: &Path, input_label: &str, kernel: &CombatKernel<'_>, config: &RankingConfig) -> Result<SurvivorRankingReport> {
    if config.food_slots < 0 {
        bail!("food_slots cannot be negative");
    }
    if config.panel_size < 1 {
        bail!("panel_size must be positive");
    }
    if config.heal_per_eat <= 0 {
        bail!("heal_per_eat must be positive");
    }
    let penalties = validated_penalties(config)?;
    let loaded = load_ranking_candidates(path, kernel)?;
    let candidates = loaded.candidates;
    let selection = select_panel(&candidates, (config.panel_size + 1).min(candidates.len()));
    let actual_panel_size = config.panel_size.min(candidates.len());
    let panel: Vec<usize> = selection.selected[..actual_panel_size].to_vec();
    let reserve = selection.selected.get(actual_panel_size).copied();
    let panel_reasons: BTreeMap<String, Vec<String>> = panel
        .iter()
        .map(|&i| (candidates[i].candidate_id.clone(), selection.reasons[&candidates[i].candidate_id].clone()))
        .collect();
    let races = race_scenarios(
        &candidates,
        &RaceConfig {
            panel: &panel,
            self_matchup_reserve: reserve,
            eat_penalties: &penalties,
            food_slots: config.food_slots,
            heal_per_eat: config.heal_per_eat,
            successful_zero_to_one: kernel.zero_to_one,
        },
    );
    let scores = category_scores(&candidates, &races);
    let niche_flags = extreme_flags(&candidates, &panel_reasons);
    let overall: Vec<Rational> = scores.par_iter().map(|s| Rational::mean(&s.values().cloned().collect::<Vec<_>>())).collect();
    let order = ranking_order(&candidates, &overall, &scores);
    let count = candidates.len();
    let mut races = races.into_iter().map(Some).collect::<Vec<_>>();
    let mut scores = scores.into_iter().map(Some).collect::<Vec<_>>();
    let mut niche_flags = niche_flags.into_iter().map(Some).collect::<Vec<_>>();
    let rankings = order
        .iter()
        .enumerate()
        .map(|(position, &index)| {
            let rank = position + 1;
            let flags = niche_flags[index].take().expect("each index once");
            let seed_reasons = panel_reasons.get(&candidates[index].candidate_id).cloned().unwrap_or_default();
            let category_scores = scores[index].take().expect("each index once");
            let mut strongest: Vec<&str> = category_scores.keys().copied().collect();
            strongest.sort_by(|a, b| category_scores[b].cmp(&category_scores[a]).then_with(|| a.cmp(b)));
            let mut rank_reasons: Vec<String> = strongest.iter().take(2).map(|name| format!("strong_category:{name}")).collect();
            rank_reasons.extend(flags.iter().cloned());
            RankedCandidate {
                index,
                rank,
                tier: tier_for(rank, count, !flags.is_empty() || !seed_reasons.is_empty()),
                overall_score: overall[index].clone(),
                category_scores,
                race_scenarios: races[index].take().expect("each index once"),
                niche_flags: flags,
                rank_reasons,
                simulator_seed_reasons: seed_reasons,
            }
        })
        .collect();
    Ok(SurvivorRankingReport {
        input_path: input_label.to_owned(),
        panel_candidate_ids: panel.iter().map(|&i| candidates[i].candidate_id.clone()).collect(),
        panel_reasons,
        ranking_self_matchup_reserve_candidate_id: reserve.map(|i| candidates[i].candidate_id.clone()),
        candidates,
        rankings,
        config: RankingConfig {
            eat_penalties: penalties,
            ..config.clone()
        },
        source_fields: loaded.source_fields,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn midranks_match_bisect_formula() {
        let values: Vec<Rational> = [3, 1, 3, 2].iter().map(|v| Rational::from(*v)).collect();
        // sorted: 1,2,3,3 -> bisect_left+bisect_right-1: 3 => 2+4-1=5, 1 => 0, 2 => 2.
        assert_eq!(midrank_integers(&values), vec![5, 0, 5, 2]);
        assert_eq!(midrank_percentiles(&values)[0], Rational::new(5, 6));
        assert_eq!(midrank_percentiles(&values[..1]), vec![Rational::one()]);
    }

    #[test]
    fn tiers_follow_cutoffs() {
        assert_eq!(tier_for(1, 1000, false), "S");
        assert_eq!(tier_for(11, 1000, false), "A");
        assert_eq!(tier_for(51, 1000, false), "B");
        assert_eq!(tier_for(201, 1000, true), "N");
        assert_eq!(tier_for(201, 1000, false), "C");
    }
}
