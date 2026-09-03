//! Stage 5: KO-switch kit expansion and ranking.  There is no Python
//! reference for this stage; the design lives in
//! `docs/design/2026-09-01-ko-kit-expansion-design.md`.

pub mod enumerate;
pub mod ko;
pub mod loadout;
pub mod magic;
pub mod output;
pub mod race;
pub mod scores;

use std::collections::{BTreeMap, HashMap};

use anyhow::{anyhow, Result};

use crate::ranking::{RaceScenario, RankingCandidate, RankingStyle};
use crate::rational::Rational;

pub const STACK_SCOPE: &str = "rapid_shortbow_arrow_plus_one_melee_ko_hit_treated_as_unreactable_no_distance_or_flight";
pub const SWITCH_CADENCE_SCOPE: &str = "primary_then_ko_weapon_on_carried_cooldown_no_projectile_delay";
pub const MELEE_DAMAGE_TYPES: [&str; 3] = ["stab", "slash", "crush"];
pub const STACK_WEAPON_TYPE: &str = "shortbow";
pub const STACK_STYLE_FAMILY: &str = "rapid";
pub const CATEGORIES: [&str; 6] = ["sustain", "race", "burst", "defence", "utility", "ko_switch"];
pub const TIE_BREAK: [&str; 6] = ["race", "ko_switch", "burst", "sustain", "defence", "utility"];

/// How often the parallel KO/race passes log progress to stderr.
pub(super) const PROGRESS_EVERY: usize = 100_000;

/// Name-indexed access to the manifest columns Stage 4 keeps as `source_values`.
pub struct SourceColumns {
    index: HashMap<String, usize>,
}

impl SourceColumns {
    pub fn new(source_fields: &[String]) -> SourceColumns {
        SourceColumns {
            index: source_fields.iter().enumerate().map(|(i, n)| (n.clone(), i)).collect(),
        }
    }

    pub fn get<'a>(&self, candidate: &'a RankingCandidate, name: &str) -> Result<&'a str> {
        let index = self.index.get(name).ok_or_else(|| anyhow!("Survivor manifest has no column {name:?}"))?;
        candidate
            .source_values
            .get(*index)
            .map(|v| v.trim())
            .ok_or_else(|| anyhow!("Candidate {} is missing column {name:?}", candidate.candidate_id))
    }

    pub fn int(&self, candidate: &RankingCandidate, name: &str) -> Result<i64> {
        let text = self.get(candidate, name)?;
        text.parse::<i64>()
            .map_err(|_| anyhow!("Candidate {} column {name:?} is not an integer: {text:?}", candidate.candidate_id))
    }

    pub fn optional_int(&self, candidate: &RankingCandidate, name: &str) -> Result<Option<i64>> {
        if self.get(candidate, name)?.is_empty() {
            Ok(None)
        } else {
            self.int(candidate, name).map(Some)
        }
    }
}

#[derive(Clone, Debug)]
pub struct KoLoadout {
    pub weapon_id: i64,
    pub weapon_name: String,
    pub two_handed: bool,
    /// Amulet swapped in with the KO weapon (one extra switch slot), if any.
    pub neck_id: Option<i64>,
    pub neck_name: Option<String>,
    pub styles: Vec<RankingStyle>,
    pub switch_slots: i64,
}

#[derive(Clone, Debug)]
pub struct Kit {
    pub kit_id: String,
    /// Index into the survivor candidate list.
    pub primary: usize,
    pub ko: Option<KoLoadout>,
    /// Spell carried as runes (a second variant of the kit), if any.
    pub spell: Option<magic::SpellChoice>,
    pub food_slots: i64,
}

impl Kit {
    pub fn is_baseline(&self) -> bool {
        self.ko.is_none()
    }

    /// Styles the KO summary columns describe: the KO weapon's, or the primary's for a baseline kit.
    pub fn ko_styles<'a>(&'a self, primary: &'a RankingCandidate) -> &'a [RankingStyle] {
        self.ko.as_ref().map_or(primary.styles.as_slice(), |k| k.styles.as_slice())
    }
}

/// Scoring reductions of the stack and switch-cadence KO tables (kept for every kit).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct KitKo {
    /// Mean over defence states of P(arrow + one KO hit >= hp); all zero when the kit cannot stack.
    pub stack_by_hp: [Rational; 6],
    pub stack_mean: Rational,
    /// Mean over defence states and HP thresholds of the best switch-cadence KO probability per window.
    pub switch_by_window: [Rational; 4],
    /// Kill pressure: P(best unanswerable burst > one heal), mean over defence states.
    pub pressure: Rational,
    /// Expected damage beyond one heal when the burst beats it (HP), mean over defence states.
    pub bite: Rational,
    /// P(best unanswerable burst >= FINISH_THRESHOLDS[i]), mean over defence states.
    pub finish: [Rational; 3],
    /// Highest possible unanswerable burst: arrow max + KO max for stack kits, else the hardest single hit (potted when carried).
    pub max_burst: i64,
}

/// HP values at which the "finish" probability is reported.
pub const FINISH_THRESHOLDS: [i64; 3] = [10, 15, 20];

/// Full KO tables (report preview only).
#[derive(Clone, Debug)]
pub struct KitKoTables {
    /// `label:hp` -> P(arrow + one KO hit >= hp).
    pub stack: BTreeMap<String, Rational>,
    /// `label:window:hp` -> best P(total >= hp) over no-switch and switch sequences.
    pub switch: BTreeMap<String, Rational>,
    pub summary: KitKo,
}

#[derive(Clone, Debug)]
pub struct KitConfig {
    pub panel_size: usize,
    pub inventory_slots: i64,
    pub heal_per_eat: i64,
    pub eat_penalties: Vec<i64>,
    pub preview_size: usize,
    /// Strength potions carried: one inventory slot each; melee hits in the KO tables use the potted max hit when >= 1.
    pub strength_potions: i64,
    /// Keep at most this many KO loadouts per build (best potted max hit, then attack roll); 0 = all.
    pub max_ko_options: usize,
    /// Keep only the union of the top N survivors by sustained DPT, by Strength (then potted max hit),
    /// and by physical defence before expanding kits; 0 = every survivor.
    pub max_builds: usize,
    /// Add a runes variant of every kit carrying the best out-hitting F2P spell.
    pub magic: bool,
}

impl Default for KitConfig {
    fn default() -> KitConfig {
        KitConfig {
            panel_size: 32,
            inventory_slots: 28,
            heal_per_eat: 14,
            eat_penalties: vec![3, 0],
            preview_size: 50,
            strength_potions: 1,
            magic: true,
            max_ko_options: 0,
            max_builds: 0,
        }
    }
}

#[derive(Clone, Debug)]
pub struct RankedKit {
    /// Index into `KitRankingReport::kits`.
    pub index: usize,
    pub rank: usize,
    /// Rank under the kill-pressure ordering (pressure, bite, race margin, kit id).
    pub pressure_rank: usize,
    pub tier: &'static str,
    pub overall_score: Rational,
    pub category_scores: BTreeMap<&'static str, Rational>,
    pub race_scenarios: Vec<RaceScenario>,
    pub niche_flags: Vec<String>,
    pub rank_reasons: Vec<String>,
    pub simulator_seed_reasons: Vec<String>,
}

pub struct KitRankingReport {
    pub input_path: String,
    pub screen_report_path: String,
    pub candidates: Vec<RankingCandidate>,
    pub kits: Vec<Kit>,
    pub ko_metrics: Vec<KitKo>,
    /// Full KO tables for the kits in the report preview, keyed by kit index.
    pub preview_tables: HashMap<usize, KitKoTables>,
    pub rankings: Vec<RankedKit>,
    pub panel_candidate_ids: Vec<String>,
    pub panel_reasons: BTreeMap<String, Vec<String>>,
    pub ranking_self_matchup_reserve_candidate_id: Option<String>,
    pub config: KitConfig,
}

impl KitRankingReport {
    pub fn tier_counts(&self) -> BTreeMap<&'static str, usize> {
        let mut counts: BTreeMap<&'static str, usize> = ["S", "A", "B", "N", "C"].into_iter().map(|t| (t, 0)).collect();
        for ranked in &self.rankings {
            *counts.get_mut(ranked.tier).expect("known tier") += 1;
        }
        counts
    }
}

/// Shared test scaffolding: the real ruleset and a synthetic survivor candidate.
#[cfg(test)]
pub(crate) mod testing {
    use super::*;
    use crate::items::{load_items, EquipmentItem};
    use crate::mechanics::MechanicRegistry;
    use std::path::PathBuf;

    pub fn ruleset_dir() -> PathBuf {
        PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/../rulesets/osrs-f2p-v1"))
    }

    pub fn ruleset() -> (MechanicRegistry, Vec<EquipmentItem>) {
        let dir = ruleset_dir();
        (
            MechanicRegistry::load(&dir.join("mechanics.json")).unwrap(),
            load_items(&dir.join("items.json")).unwrap(),
        )
    }

    /// A CB30-shaped survivor (attack 40 / strength 31 / ranged 30 / magic 1 / prayer 1 / def 1 / hp 30)
    /// with the given `source_values`; every numeric field is a plain placeholder.
    pub fn candidate(source: &[(&str, &str)]) -> (RankingCandidate, SourceColumns) {
        let fields: Vec<String> = source.iter().map(|(k, _)| k.to_string()).collect();
        let values: Vec<String> = source.iter().map(|(_, v)| v.to_string()).collect();
        let style = RankingStyle {
            style_id: "aggressive_slash".into(),
            damage_type: "slash".into(),
            attack_roll: 3000,
            max_hit: 8,
            potted_max_hit: 10,
            cooldown_ticks: 4,
            maximum_range: 1,
        };
        let candidate = RankingCandidate {
            candidate_id: "test-candidate".into(),
            resolved_signature: "sig".into(),
            profile_id: 1,
            levels: [40, 31, 30, 1, 1, 1, 30],
            styles: vec![style],
            sustained_dpt: [Rational::one(), Rational::one(), Rational::one()],
            ko_by_window: [Rational::zero(), Rational::zero(), Rational::zero(), Rational::zero()],
            defence_rolls: [1000, 1000, 1000, 1000],
            magic_attack_bonus: 0,
            magic_defence_bonus: 0,
            prayer_bonus: 0,
            weapon_type: "scimitar".into(),
            weapon_name: "Rune scimitar".into(),
            weapon_slot: "weapon".into(),
            two_handed: false,
            equipment_names: std::array::from_fn(|_| "EMPTY".into()),
            sustain_average: Rational::one(),
            sustain_worst: Rational::one(),
            physical_defence_average: Rational::from(1000),
            max_hit: 8,
            maximum_attack_roll: 3000,
            potted_max_hit: 10,
            maximum_range: 1,
            damage_types: vec!["slash".into()],
            source_values: values,
        };
        (candidate, SourceColumns::new(&fields))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn source_columns_look_up_by_name() {
        let (candidate, columns) = testing::candidate(&[("weapon_id", "1333"), ("shield_id", "")]);
        assert_eq!(columns.int(&candidate, "weapon_id").unwrap(), 1333);
        assert_eq!(columns.optional_int(&candidate, "shield_id").unwrap(), None);
        assert!(columns.get(&candidate, "missing").is_err());
    }
}
