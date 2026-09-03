//! Six-category kit percentiles, ordering, tiers, and the `rank_kits` orchestration.

use std::cmp::Ordering;
use std::collections::{BTreeMap, HashMap};
use std::path::Path;

use anyhow::{bail, Result};
use rayon::prelude::*;

use super::enumerate::{enumerate_kits, KitLimits};
use super::ko::{all_kit_ko, kit_ko_tables, load_representative_rolls, PmfCache};
use super::magic::{candidate_magic_defence_roll, representative_magic_rolls, SpellBook, MAGIC_DAMAGE_TYPE};
use super::race::kit_race_scenarios;
use super::{Kit, KitConfig, KitKo, KitKoTables, KitRankingReport, RankedKit, SourceColumns, CATEGORIES, TIE_BREAK};
use crate::combat::CombatKernel;
use crate::items::EquipmentItem;
use crate::ranking::load::load_ranking_candidates;
use crate::ranking::panel::select_panel;
use crate::ranking::race::RaceConfig;
use crate::ranking::scores::{extreme_flags, midrank_percentiles, tier_for, validate_eat_penalties};
use crate::ranking::{RaceScenario, RankingCandidate, DAMAGE_TYPES, DEFENCE_STATES, WINDOWS};
use crate::rational::Rational;

fn primary_column(candidates: &[RankingCandidate], kits: &[Kit], value: impl Fn(&RankingCandidate) -> Rational + Sync + Send) -> Vec<Rational> {
    kits.par_iter().map(|kit| value(&candidates[kit.primary])).collect()
}

fn penalty_indices(first: &[RaceScenario]) -> (usize, usize) {
    let position = |penalty: i64| first.iter().position(|s| s.eat_penalty == penalty);
    let primary = position(3).unwrap_or(0);
    (primary, position(0).unwrap_or(primary))
}

fn metric_groups(candidates: &[RankingCandidate], kits: &[Kit], ko_metrics: &[KitKo], races: &[Vec<RaceScenario>]) -> Vec<(&'static str, Vec<Rational>)> {
    let (primary, sensitivity) = penalty_indices(&races[0]);
    let mut groups: Vec<(&'static str, Vec<Rational>)> = Vec::new();
    for index in 0..DEFENCE_STATES.len() {
        groups.push(("sustain", primary_column(candidates, kits, |c| c.sustained_dpt[index].clone())));
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
        groups.push(("burst", primary_column(candidates, kits, |c| c.ko_by_window[index].clone())));
    }
    groups.push(("burst", primary_column(candidates, kits, |c| Rational::from(c.max_hit))));
    groups.push(("burst", primary_column(candidates, kits, |c| Rational::from(c.potted_max_hit))));
    for index in 0..DAMAGE_TYPES.len() {
        groups.push(("defence", primary_column(candidates, kits, |c| Rational::from(c.defence_rolls[index]))));
    }
    groups.push(("defence", primary_column(candidates, kits, |c| Rational::from(c.magic_defence_bonus))));
    groups.push(("utility", primary_column(candidates, kits, |c| Rational::from(c.maximum_range))));
    groups.push(("utility", primary_column(candidates, kits, |c| Rational::from(c.styles.len() as i64))));
    groups.push(("utility", primary_column(candidates, kits, |c| Rational::from(c.prayer_level()))));
    groups.push(("utility", primary_column(candidates, kits, |c| Rational::from(c.prayer_bonus))));
    groups.push(("utility", primary_column(candidates, kits, |c| Rational::from(c.magic_attack_bonus))));
    groups.push(("ko_switch", ko_metrics.par_iter().map(|m| m.stack_mean.clone()).collect()));
    for index in 0..WINDOWS.len() {
        groups.push(("ko_switch", ko_metrics.par_iter().map(|m| m.switch_by_window[index].clone()).collect()));
    }
    groups.push((
        "ko_switch",
        kits.par_iter()
            .map(|kit| Rational::from(kit.ko_styles(&candidates[kit.primary]).iter().map(|s| s.max_hit).max().unwrap_or(0)))
            .collect(),
    ));
    groups
}

/// Equal-weight mean percentile per category over the kit population, one map per kit.
pub fn kit_category_scores(
    candidates: &[RankingCandidate],
    kits: &[Kit],
    ko_metrics: &[KitKo],
    races: &[Vec<RaceScenario>],
) -> Vec<BTreeMap<&'static str, Rational>> {
    let groups = metric_groups(candidates, kits, ko_metrics, races);
    let percentiles: Vec<(&'static str, Vec<Rational>)> = groups.par_iter().map(|(category, values)| (*category, midrank_percentiles(values))).collect();
    let counts: BTreeMap<&str, i64> = CATEGORIES
        .iter()
        .map(|c| (*c, percentiles.iter().filter(|(cat, _)| cat == c).count() as i64))
        .collect();
    (0..kits.len())
        .into_par_iter()
        .map(|index| {
            CATEGORIES
                .iter()
                .map(|category| {
                    let total = percentiles
                        .iter()
                        .filter(|(cat, _)| cat == category)
                        .fold(Rational::zero(), |acc, (_, values)| acc + &values[index]);
                    (*category, total / Rational::from(counts[category]))
                })
                .collect()
        })
        .collect()
}

pub fn kit_order(kits: &[Kit], overall: &[Rational], scores: &[BTreeMap<&'static str, Rational>]) -> Vec<usize> {
    let mut order: Vec<usize> = (0..kits.len()).collect();
    order.par_sort_by(|&a, &b| {
        overall[b]
            .cmp(&overall[a])
            .then_with(|| {
                TIE_BREAK
                    .iter()
                    .map(|key| scores[b][key].cmp(&scores[a][key]))
                    .find(|o| *o != Ordering::Equal)
                    .unwrap_or(Ordering::Equal)
            })
            .then_with(|| kits[a].kit_id.cmp(&kits[b].kit_id))
    });
    order
}

/// Kill-pressure ordering: pressure, then bite, then penalty-3 mean race margin, then kit id.
pub fn pressure_order(kits: &[Kit], ko_metrics: &[KitKo], races: &[Vec<RaceScenario>]) -> Vec<usize> {
    let (primary, _) = penalty_indices(&races[0]);
    let mut order: Vec<usize> = (0..kits.len()).collect();
    order.par_sort_by(|&a, &b| {
        ko_metrics[b]
            .pressure
            .cmp(&ko_metrics[a].pressure)
            .then_with(|| ko_metrics[b].bite.cmp(&ko_metrics[a].bite))
            .then_with(|| races[b][primary].mean_margin_fish.cmp(&races[a][primary].mean_margin_fish))
            .then_with(|| kits[a].kit_id.cmp(&kits[b].kit_id))
    });
    order
}

/// `ranks[index]` = 1-based position of kit `index` in `order`.
fn positions(order: &[usize]) -> Vec<usize> {
    let mut ranks = vec![0usize; order.len()];
    for (position, &index) in order.iter().enumerate() {
        ranks[index] = position + 1;
    }
    ranks
}

/// Top-N union by attrition (medium-defence DPT), by KO potential (Strength, then potted max
/// hit) and by tankiness (physical defence average); ties by candidate id.  Order is preserved.
pub fn shortlist_builds(candidates: Vec<RankingCandidate>, max_builds: usize) -> Vec<RankingCandidate> {
    if max_builds == 0 || candidates.len() <= max_builds {
        return candidates;
    }
    let mut keep = vec![false; candidates.len()];
    let mut mark = |mut order: Vec<usize>, key: &dyn Fn(usize) -> std::cmp::Reverse<(Rational, i64, i64)>| {
        order.sort_by(|&a, &b| key(a).cmp(&key(b)).then_with(|| candidates[a].candidate_id.cmp(&candidates[b].candidate_id)));
        for &index in order.iter().take(max_builds) {
            keep[index] = true;
        }
    };
    let all: Vec<usize> = (0..candidates.len()).collect();
    mark(all.clone(), &|i| std::cmp::Reverse((candidates[i].sustained_dpt[1].clone(), 0, 0)));
    mark(all.clone(), &|i| {
        std::cmp::Reverse((Rational::from(candidates[i].levels[1]), candidates[i].potted_max_hit, candidates[i].max_hit))
    });
    mark(all, &|i| {
        std::cmp::Reverse((candidates[i].physical_defence_average.clone(), candidates[i].levels[5], 0))
    });
    candidates
        .into_iter()
        .zip(keep)
        .filter(|(_, kept)| *kept)
        .map(|(candidate, _)| candidate)
        .collect()
}

fn validate(config: &KitConfig) -> Result<Vec<i64>> {
    if config.inventory_slots < 0 {
        bail!("inventory_slots cannot be negative");
    }
    if config.panel_size < 1 {
        bail!("panel_size must be positive");
    }
    if config.heal_per_eat <= 0 {
        bail!("heal_per_eat must be positive");
    }
    if config.strength_potions < 0 {
        bail!("strength_potions cannot be negative");
    }
    validate_eat_penalties(&config.eat_penalties)
}

// Private assembly step: every argument is a distinct per-kit or per-candidate column that
// `rank_kits` has already computed, so a parameter struct would only rename the one call site.
#[allow(clippy::too_many_arguments)]
fn build_rankings(
    candidates: &[RankingCandidate],
    kits: &[Kit],
    order: &[usize],
    overall: &[Rational],
    scores: Vec<BTreeMap<&'static str, Rational>>,
    races: Vec<Vec<RaceScenario>>,
    candidate_flags: &[Vec<String>],
    panel_reasons: &BTreeMap<String, Vec<String>>,
    pressure_ranks: &[usize],
) -> Vec<RankedKit> {
    let count = kits.len();
    let mut races = races.into_iter().map(Some).collect::<Vec<_>>();
    let mut scores = scores.into_iter().map(Some).collect::<Vec<_>>();
    order
        .iter()
        .enumerate()
        .map(|(position, &index)| {
            let rank = position + 1;
            let primary = &candidates[kits[index].primary];
            let flags = candidate_flags[kits[index].primary].clone();
            let seed_reasons = panel_reasons.get(&primary.candidate_id).cloned().unwrap_or_default();
            let category_scores = scores[index].take().expect("each index once");
            let mut strongest: Vec<&str> = category_scores.keys().copied().collect();
            strongest.sort_by(|a, b| category_scores[b].cmp(&category_scores[a]).then_with(|| a.cmp(b)));
            let mut rank_reasons: Vec<String> = strongest.iter().take(2).map(|name| format!("strong_category:{name}")).collect();
            rank_reasons.extend(flags.iter().cloned());
            RankedKit {
                index,
                rank,
                pressure_rank: pressure_ranks[index],
                tier: tier_for(rank, count, !flags.is_empty() || !seed_reasons.is_empty()),
                overall_score: overall[index].clone(),
                category_scores,
                race_scenarios: races[index].take().expect("each index once"),
                niche_flags: flags,
                rank_reasons,
                simulator_seed_reasons: seed_reasons,
            }
        })
        .collect()
}

/// Expand every survivor into kits and rank the kit population.
pub fn rank_kits(
    manifest: &Path,
    input_label: &str,
    screen_report: &Path,
    screen_label: &str,
    kernel: &CombatKernel<'_>,
    items: &[EquipmentItem],
    config: &KitConfig,
) -> Result<KitRankingReport> {
    let started = std::time::Instant::now();
    let phase = |name: &str| eprintln!("[expand-ko-kits] {name} at {:.1}s", started.elapsed().as_secs_f64());
    let penalties = validate(config)?;
    let mut rolls = load_representative_rolls(screen_report)?;
    let loaded = load_ranking_candidates(manifest, kernel)?;
    let candidates = shortlist_builds(loaded.candidates, config.max_builds);
    eprintln!("[expand-ko-kits] {} survivors after the build shortlist", candidates.len());
    phase("manifest loaded");
    let columns = SourceColumns::new(&loaded.source_fields);
    let book = if config.magic { Some(SpellBook::load(kernel.mechanics)?) } else { None };
    let magic_rolls: Vec<i64> = candidates.iter().map(candidate_magic_defence_roll).collect();
    for (label, roll) in representative_magic_rolls(&candidates)? {
        rolls.entry(label).or_default().insert(MAGIC_DAMAGE_TYPE.to_owned(), roll);
    }
    let selection = select_panel(&candidates, (config.panel_size + 1).min(candidates.len()));
    let actual_panel_size = config.panel_size.min(candidates.len());
    let panel: Vec<usize> = selection.selected[..actual_panel_size].to_vec();
    let reserve = selection.selected.get(actual_panel_size).copied();
    let panel_reasons: BTreeMap<String, Vec<String>> = panel
        .iter()
        .map(|&i| (candidates[i].candidate_id.clone(), selection.reasons[&candidates[i].candidate_id].clone()))
        .collect();
    let kits = enumerate_kits(&candidates, &columns, items, kernel, book.as_ref(), KitLimits::from(config))?;
    eprintln!("[expand-ko-kits] {} survivors -> {} kits", candidates.len(), kits.len());
    phase("kits enumerated");
    let cache = PmfCache::build(kernel, &rolls, &candidates, &kits, config.heal_per_eat, config.strength_potions >= 1)?;
    eprintln!("[expand-ko-kits] cached {} style distributions", cache.len());
    phase("cache built");
    let ko_metrics = all_kit_ko(&cache, &candidates, &kits);
    phase("ko tables done");
    let races = kit_race_scenarios(
        &candidates,
        &magic_rolls,
        &kits,
        &RaceConfig {
            panel: &panel,
            self_matchup_reserve: reserve,
            eat_penalties: &penalties,
            food_slots: config.inventory_slots,
            heal_per_eat: config.heal_per_eat,
            successful_zero_to_one: kernel.zero_to_one,
        },
    );
    phase("races done");
    let scores = kit_category_scores(&candidates, &kits, &ko_metrics, &races);
    phase("scores done");
    let candidate_flags = extreme_flags(&candidates, &panel_reasons);
    let overall: Vec<Rational> = scores.par_iter().map(|s| Rational::mean(&s.values().cloned().collect::<Vec<_>>())).collect();
    let order = kit_order(&kits, &overall, &scores);
    let preview_tables: HashMap<usize, KitKoTables> = order
        .iter()
        .take(config.preview_size)
        .map(|&i| (i, kit_ko_tables(&cache, &candidates[kits[i].primary], &kits[i])))
        .collect();
    phase("preview tables done");
    let pressure_ranks = positions(&pressure_order(&kits, &ko_metrics, &races));
    let ranked = build_rankings(
        &candidates,
        &kits,
        &order,
        &overall,
        scores,
        races,
        &candidate_flags,
        &panel_reasons,
        &pressure_ranks,
    );
    Ok(KitRankingReport {
        input_path: input_label.to_owned(),
        screen_report_path: screen_label.to_owned(),
        panel_candidate_ids: panel.iter().map(|&i| candidates[i].candidate_id.clone()).collect(),
        panel_reasons,
        ranking_self_matchup_reserve_candidate_id: reserve.map(|i| candidates[i].candidate_id.clone()),
        candidates,
        kits,
        ko_metrics,
        preview_tables,
        rankings: ranked,
        config: KitConfig {
            eat_penalties: penalties,
            ..config.clone()
        },
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kits::testing::candidate;
    use crate::kits::KoLoadout;
    use crate::ranking::RankingStyle;

    fn ko_metrics(stack_mean: i64, window: i64) -> KitKo {
        KitKo {
            stack_by_hp: std::array::from_fn(|_| Rational::from(stack_mean)),
            stack_mean: Rational::from(stack_mean),
            switch_by_window: std::array::from_fn(|_| Rational::from(window)),
            pressure: Rational::from(stack_mean),
            bite: Rational::from(stack_mean),
            finish: std::array::from_fn(|_| Rational::from(stack_mean)),
            max_burst: 0,
        }
    }

    #[test]
    fn pressure_order_prefers_pressure_then_bite_then_race() {
        let kits: Vec<Kit> = ["a", "b", "c"]
            .iter()
            .map(|id| Kit {
                kit_id: id.to_string(),
                primary: 0,
                ko: None,
                spell: None,
                food_slots: 28,
            })
            .collect();
        let mut metrics = vec![ko_metrics(0, 1), ko_metrics(1, 1), ko_metrics(1, 1)];
        metrics[2].bite = Rational::from(5);
        let races = vec![scenario(9), scenario(4), scenario(4)];
        assert_eq!(pressure_order(&kits, &metrics, &races), vec![2, 1, 0]);
        assert_eq!(positions(&[2, 1, 0]), vec![3, 2, 1]);
    }

    fn scenario(mean: i64) -> Vec<RaceScenario> {
        [3, 0]
            .iter()
            .map(|&p| RaceScenario {
                eat_penalty: p,
                opponent_count: 1,
                worst_margin_fish: Rational::from(mean),
                tenth_percentile_margin_fish: Rational::from(mean),
                mean_margin_fish: Rational::from(mean),
                win_fraction: Rational::one(),
            })
            .collect()
    }

    #[test]
    fn ko_switch_category_uses_stack_switch_and_ko_max_hit() {
        let (primary, _) = candidate(&[]);
        let candidates = vec![primary];
        let style = RankingStyle {
            style_id: "aggressive_slash".into(),
            damage_type: "slash".into(),
            attack_roll: 1,
            max_hit: 14,
            potted_max_hit: 16,
            cooldown_ticks: 7,
            maximum_range: 1,
        };
        let kits = vec![
            Kit {
                kit_id: "a".into(),
                primary: 0,
                ko: None,
                spell: None,
                food_slots: 28,
            },
            Kit {
                kit_id: "b".into(),
                primary: 0,
                ko: Some(KoLoadout {
                    weapon_id: 1,
                    weapon_name: "x".into(),
                    two_handed: true,
                    neck_id: None,
                    neck_name: None,
                    switch_slots: 1,
                    styles: vec![style],
                }),
                spell: None,
                food_slots: 27,
            },
        ];
        let metrics = vec![ko_metrics(0, 1), ko_metrics(1, 2)];
        let races = vec![scenario(5), scenario(4)];
        let scores = kit_category_scores(&candidates, &kits, &metrics, &races);
        assert_eq!(scores.len(), 2);
        assert!(scores[1]["ko_switch"] > scores[0]["ko_switch"]);
        assert!(scores[0]["race"] > scores[1]["race"]);
        assert_eq!(
            scores[0]["sustain"], scores[1]["sustain"],
            "primary-derived categories tie for the same survivor"
        );
        assert!(scores[0].keys().eq(["burst", "defence", "ko_switch", "race", "sustain", "utility"].iter()));
    }

    #[test]
    fn kit_order_breaks_ties_by_race_then_ko_switch_then_kit_id() {
        let kits: Vec<Kit> = ["z", "a"]
            .iter()
            .map(|id| Kit {
                kit_id: id.to_string(),
                primary: 0,
                ko: None,
                spell: None,
                food_slots: 28,
            })
            .collect();
        let overall = vec![Rational::one(), Rational::one()];
        let same: BTreeMap<&'static str, Rational> = CATEGORIES.iter().map(|c| (*c, Rational::one())).collect();
        assert_eq!(
            kit_order(&kits, &overall, &[same.clone(), same.clone()]),
            vec![1, 0],
            "equal scores fall back to kit_id"
        );
        let mut better_ko = same.clone();
        better_ko.insert("ko_switch", Rational::from(2));
        assert_eq!(kit_order(&kits, &overall, &[better_ko, same]), vec![0, 1]);
    }
    #[test]
    fn shortlist_keeps_the_union_of_three_top_lists() {
        let (base, _) = candidate(&[]);
        let mut fast = base.clone();
        fast.candidate_id = "fast".into();
        fast.sustained_dpt = [Rational::from(9), Rational::from(9), Rational::from(9)];
        let mut strong = base.clone();
        strong.candidate_id = "strong".into();
        strong.levels[1] = 90;
        let mut tank = base.clone();
        tank.candidate_id = "tank".into();
        tank.physical_defence_average = Rational::from(9999);
        let mut dull = base.clone();
        dull.candidate_id = "dull".into();
        let kept = shortlist_builds(vec![dull, fast, strong, tank], 1);
        let ids: Vec<&str> = kept.iter().map(|c| c.candidate_id.as_str()).collect();
        assert_eq!(ids, vec!["fast", "strong", "tank"]);
        assert_eq!(shortlist_builds(vec![base.clone(), base], 0).len(), 2);
    }
}
