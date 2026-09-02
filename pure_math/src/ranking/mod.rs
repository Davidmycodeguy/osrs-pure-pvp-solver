//! Survivor priority ranking (port of `pure_solver.survivor_ranking`).
//!
//! Ranks every resolved survivor without deleting any row: a farthest-point
//! simulator seed panel, a notional attrition race against that panel, and
//! equal-weight population-percentile category scores.  Outputs are written in
//! the exact shapes the Python module produced.

pub mod load;
pub mod output;
pub mod panel;
pub mod race;
pub mod scores;

use std::collections::BTreeMap;

use crate::rational::Rational;

pub const DEFENCE_STATES: [&str; 3] = ["low", "medium", "high"];
pub const WINDOWS: [i64; 4] = [4, 5, 8, 12];
pub const HP_THRESHOLDS: [i64; 6] = [5, 10, 15, 20, 25, 30];
pub const DAMAGE_TYPES: [&str; 4] = ["stab", "slash", "crush", "ranged"];
pub const DEFAULT_EAT_PENALTIES: [i64; 2] = [3, 0];
pub const CADENCE_SCOPE: &str = "repeated_weapon_cooldown_only_no_projectile_delay_or_switching";
pub const LEVEL_NAMES: [&str; 7] = ["attack", "strength", "ranged", "magic", "prayer", "defence", "hitpoints"];
pub const EQUIPMENT_NAME_COLUMNS: [&str; 8] = [
    "head_name",
    "neck_name",
    "body_name",
    "legs_name",
    "hands_name",
    "weapon_name",
    "ammo_name",
    "shield_name",
];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RankingStyle {
    pub style_id: String,
    pub damage_type: String,
    pub attack_roll: i64,
    pub max_hit: i64,
    pub potted_max_hit: i64,
    pub cooldown_ticks: i64,
    pub maximum_range: i64,
}

/// One resolved survivor row plus the derived aggregates the ranker reads repeatedly.
#[derive(Clone, Debug)]
pub struct RankingCandidate {
    pub candidate_id: String,
    pub resolved_signature: String,
    pub profile_id: i64,
    pub levels: [i64; 7],
    pub styles: Vec<RankingStyle>,
    pub sustained_dpt: [Rational; 3],
    pub ko_by_window: [Rational; 4],
    pub defence_rolls: [i64; 4],
    pub magic_attack_bonus: i64,
    pub magic_defence_bonus: i64,
    pub prayer_bonus: i64,
    pub weapon_type: String,
    pub weapon_name: String,
    pub weapon_slot: String,
    pub two_handed: bool,
    pub equipment_names: [String; 8],
    pub sustain_average: Rational,
    pub sustain_worst: Rational,
    pub physical_defence_average: Rational,
    pub max_hit: i64,
    pub maximum_attack_roll: i64,
    pub potted_max_hit: i64,
    pub maximum_range: i64,
    pub damage_types: Vec<String>,
    /// Source manifest columns echoed into the enriched ranked CSV, in header order.
    pub source_values: Vec<String>,
}

impl RankingCandidate {
    pub fn hitpoints(&self) -> i64 {
        self.levels[6]
    }

    pub fn prayer_level(&self) -> i64 {
        self.levels[4]
    }

    /// Defence roll indexed by `DAMAGE_TYPES` position.
    pub fn defence_roll_for(&self, damage_type: &str) -> i64 {
        let index = DAMAGE_TYPES.iter().position(|d| *d == damage_type).expect("validated damage type");
        self.defence_rolls[index]
    }
}

#[derive(Clone, Debug)]
pub struct RaceScenario {
    pub eat_penalty: i64,
    pub opponent_count: usize,
    pub worst_margin_fish: Rational,
    pub tenth_percentile_margin_fish: Rational,
    pub mean_margin_fish: Rational,
    pub win_fraction: Rational,
}

#[derive(Clone, Debug)]
pub struct RankedCandidate {
    /// Index into `SurvivorRankingReport::candidates`.
    pub index: usize,
    pub rank: usize,
    pub tier: &'static str,
    pub overall_score: Rational,
    /// Sorted by category name.
    pub category_scores: BTreeMap<&'static str, Rational>,
    pub race_scenarios: Vec<RaceScenario>,
    pub niche_flags: Vec<String>,
    pub rank_reasons: Vec<String>,
    pub simulator_seed_reasons: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct RankingConfig {
    pub panel_size: usize,
    pub food_slots: i64,
    pub heal_per_eat: i64,
    pub eat_penalties: Vec<i64>,
    pub preview_size: usize,
}

impl Default for RankingConfig {
    fn default() -> RankingConfig {
        RankingConfig {
            panel_size: 32,
            food_slots: 28,
            heal_per_eat: 14,
            eat_penalties: DEFAULT_EAT_PENALTIES.to_vec(),
            preview_size: 50,
        }
    }
}

pub struct SurvivorRankingReport {
    pub input_path: String,
    pub candidates: Vec<RankingCandidate>,
    pub rankings: Vec<RankedCandidate>,
    pub panel_candidate_ids: Vec<String>,
    pub panel_reasons: BTreeMap<String, Vec<String>>,
    pub ranking_self_matchup_reserve_candidate_id: Option<String>,
    pub config: RankingConfig,
    /// Manifest columns appended to the ranked CSV (not already ranked fields, not the two blobs).
    pub source_fields: Vec<String>,
}

impl SurvivorRankingReport {
    pub fn tier_counts(&self) -> BTreeMap<&'static str, usize> {
        let mut counts: BTreeMap<&'static str, usize> = ["S", "A", "B", "N", "C"].into_iter().map(|t| (t, 0)).collect();
        for ranked in &self.rankings {
            *counts.get_mut(ranked.tier).expect("known tier") += 1;
        }
        counts
    }
}

/// `_quantile`: element at floor((n-1) * numerator / denominator) of the sorted values.
pub fn quantile(values: &[Rational], numerator: usize, denominator: usize) -> Rational {
    assert!(!values.is_empty(), "Cannot take a quantile of an empty sequence");
    let mut ordered: Vec<&Rational> = values.iter().collect();
    ordered.sort();
    ordered[((ordered.len() - 1) * numerator) / denominator].clone()
}
