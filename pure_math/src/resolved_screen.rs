//! Resolved single-weapon gear screen (port of `pure_solver.resolved_gear_screen`
//! plus the static candidate construction in `pure_solver.gear_screen`).
//!
//! Every gear-matrix row becomes a candidate with exact per-style attack rolls,
//! max hits, cooldowns and defence rolls; candidates are deduplicated and
//! Pareto-pruned inside their comparison class; survivors get representative
//! cadence damage/KO summaries and are written to a manifest CSV.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::Path;
use std::sync::Arc;

use anyhow::{anyhow, bail, Result};
use rayon::prelude::*;
use serde_json::{json, Value};

use crate::canonical::{canonical_hash, canonical_json, fraction_document};
use crate::combat::{CombatKernel, DamageDistribution, ResolvedStyle, StyleInputs, DEFENCE_TYPES};
use crate::io::{csv_writer, write_json};
use crate::items::EquipmentItem;
use crate::matrix_table::{band_columns, required_columns, MatrixTable, ACCOUNT_COLUMNS, BAND_SKILLS, ITEM_SLOTS};
use crate::rational::Rational;
use crate::reduction::{reduce_candidates, CandidateReductionResult, ComparisonClass, ReductionCandidate};

pub const WINDOWS: [i64; 4] = [4, 5, 8, 12];
pub const HP_THRESHOLDS: [i64; 6] = [5, 10, 15, 20, 25, 30];
pub const CADENCE_SCOPE: &str = "repeated_weapon_cooldown_only_no_projectile_delay_or_switching";
pub const EXACT_ACCOUNT_SCOPE: &str = "exact accounts: every row carries one fully specified 1-Defence profile with reachable Hitpoints";
pub const BAND_ACCOUNT_SCOPE: &str = "gear-unlock band representatives, not exact combat-level-30 accounts";
const LABELS: [&str; 3] = ["low", "medium", "high"];

pub type RepresentativeRolls = BTreeMap<String, BTreeMap<String, i64>>;

/// Per-row data the manifest needs beyond the reduction candidate.
#[derive(Clone, Debug)]
pub struct ResolvedSource {
    pub row_index: usize,
    pub signature: String,
    pub styles: Vec<ResolvedStyle>,
    pub best_expected_damage_per_tick: BTreeMap<String, Rational>,
    pub cadence_ko_probabilities: BTreeMap<String, Rational>,
}

pub struct ResolvedScreenReport<'t> {
    pub input_path: String,
    pub table: &'t MatrixTable,
    pub reduction: CandidateReductionResult,
    pub representative_rolls: RepresentativeRolls,
    pub sources: HashMap<String, ResolvedSource>,
    pub audit_limit: usize,
    pub account_profile_scope: &'static str,
}

/// Defence rolls keyed by `(defence_level, defence_bonus, style_bonus)`.
struct DefenceRolls {
    rolls: HashMap<(i64, i64, i64), i64>,
}

impl DefenceRolls {
    fn build(kernel: &CombatKernel<'_>, table: &MatrixTable) -> Result<DefenceRolls> {
        let mut keys: HashSet<(i64, i64, i64)> = HashSet::new();
        for row in &table.rows {
            let styles = table.styles(row)?;
            let max_style = kernel.styles.max_defence_bonus(styles.iter().map(String::as_str))?;
            let mut style_bonuses = vec![max_style];
            for style in &styles {
                let (family, _) = crate::combat::StyleTable::parts(style)?;
                style_bonuses.push(kernel.styles.family(family)?.defence);
            }
            let level = table.int(row, "account_defence")?;
            for damage_type in DEFENCE_TYPES {
                let bonus = table.int(row, &format!("defence_{damage_type}"))?;
                for style_bonus in &style_bonuses {
                    keys.insert((level, bonus, *style_bonus));
                }
            }
        }
        let rolls = keys
            .into_iter()
            .map(|key| kernel.defence_roll(key.0, key.1, key.2).map(|roll| (key, roll)))
            .collect::<Result<HashMap<_, _>>>()?;
        Ok(DefenceRolls { rolls })
    }

    fn get(&self, level: i64, bonus: i64, style_bonus: i64) -> i64 {
        self.rolls[&(level, bonus, style_bonus)]
    }
}

fn quantile(sorted: &[i64], numerator: usize, denominator: usize) -> i64 {
    sorted[((sorted.len() - 1) * numerator) / denominator]
}

fn representative_rolls(kernel: &CombatKernel<'_>, table: &MatrixTable, rolls: &DefenceRolls) -> Result<RepresentativeRolls> {
    let mut values: BTreeMap<&str, Vec<i64>> = DEFENCE_TYPES.iter().map(|d| (*d, Vec::with_capacity(table.rows.len()))).collect();
    for row in &table.rows {
        let styles = table.styles(row)?;
        let style_bonus = kernel.styles.max_defence_bonus(styles.iter().map(String::as_str))?;
        let level = table.int(row, "account_defence")?;
        for damage_type in DEFENCE_TYPES {
            let bonus = table.int(row, &format!("defence_{damage_type}"))?;
            values.get_mut(damage_type).unwrap().push(rolls.get(level, bonus, style_bonus));
        }
    }
    for list in values.values_mut() {
        list.sort_unstable();
    }
    let mut result = RepresentativeRolls::new();
    for (label, numerator, denominator) in [("low", 1, 10), ("medium", 1, 2), ("high", 9, 10)] {
        result.insert(
            label.to_owned(),
            values.iter().map(|(d, list)| (d.to_string(), quantile(list, numerator, denominator))).collect(),
        );
    }
    Ok(result)
}

struct StaticCandidate {
    candidate_id: String,
    class: Arc<ComparisonClass>,
    capabilities: Vec<String>,
}

fn static_candidate(table: &MatrixTable, row: &csv::StringRecord, items_by_id: &HashMap<i64, &EquipmentItem>) -> Result<StaticCandidate> {
    let profile_id = table.int(row, "profile_id")?;
    let mut account_levels: Vec<(String, i64)> = ACCOUNT_COLUMNS
        .iter()
        .map(|column| table.int(row, column).map(|v| (column.trim_start_matches("account_").to_owned(), v)))
        .collect::<Result<_>>()?;
    let level_band: Vec<(String, i64)> = band_columns()
        .into_iter()
        .map(|column| table.int(row, &column).map(|v| (column, v)))
        .collect::<Result<_>>()?;
    let mut item_ids: BTreeMap<String, Option<i64>> = BTreeMap::new();
    for slot in ITEM_SLOTS {
        item_ids.insert(slot.to_owned(), table.optional_int(row, &format!("{slot}_id"))?);
    }
    for slot in &ITEM_SLOTS[..6] {
        if item_ids[*slot].is_none() {
            bail!("Static gear screen accepts full loadouts; row is missing {slot}");
        }
    }
    let styles = table.styles(row)?;
    if styles.is_empty() {
        bail!("Gear matrix weapon has no verified attack styles");
    }
    let attack_range = table.int(row, "weapon_attack_range")?;
    let two_handed = table.boolean(row, "two_handed")?;
    let weapon_type = match table.get(row, "weapon_type")? {
        "" => "unknown".to_owned(),
        other => other.to_owned(),
    };
    let mut selected: Vec<i64> = ITEM_SLOTS[..6]
        .iter()
        .map(|slot| table.int(row, &format!("{slot}_id")))
        .collect::<Result<_>>()?;
    for slot in ["ammo", "shield"] {
        let item_id = table.int_or(row, &format!("{slot}_id"), 0)?;
        if item_id != 0 {
            selected.push(item_id);
        }
    }
    let mut flags: HashSet<&str> = HashSet::new();
    for item_id in &selected {
        let item = items_by_id
            .get(item_id)
            .ok_or_else(|| anyhow!("Gear matrix references item {item_id} absent from the verified ruleset"))?;
        flags.extend(item.mechanic_flags.iter().map(String::as_str));
    }
    let mut mechanic_flags: Vec<String> = flags.into_iter().map(str::to_owned).collect();
    mechanic_flags.sort();
    let weapon = items_by_id[&table.int(row, "weapon_id")?];
    let mut ammo_ids = weapon.ammo_ids.clone();
    ammo_ids.sort_unstable();
    let mut spell_ids = weapon.spell_ids.clone();
    spell_ids.sort();

    let mut capabilities: HashSet<String> = styles.iter().map(|s| format!("style:{s}")).collect();
    capabilities.extend((1..=attack_range).map(|d| format!("range:at_least:{d}")));
    capabilities.extend(mechanic_flags.iter().map(|f| format!("mechanic:{f}")));
    capabilities.extend(spell_ids.iter().map(|s| format!("spell:{s}")));
    capabilities.insert(format!("weapon_type:{weapon_type}"));
    capabilities.insert(if two_handed { "switch:two_handed" } else { "switch:one_handed" }.to_owned());
    let mut capabilities: Vec<String> = capabilities.into_iter().collect();
    capabilities.sort();

    let candidate_id = canonical_hash(&json!({
        "profile_id": profile_id,
        "account_levels": account_levels.iter().cloned().collect::<BTreeMap<String, i64>>(),
        "item_ids": item_ids,
    }));
    account_levels.sort();
    let class = ComparisonClass {
        account_levels,
        attack_styles: styles,
        compatible_ammo_ids: ammo_ids,
        level_band,
        mechanic_flags,
        profile_id,
        spell_ids,
        two_handed,
        weapon_type,
    };
    Ok(StaticCandidate {
        candidate_id,
        class: Arc::new(class),
        capabilities,
    })
}

fn style_inputs(table: &MatrixTable, row: &csv::StringRecord) -> Result<StyleInputs> {
    Ok(StyleInputs {
        attack: table.int(row, "account_attack")?,
        strength: table.int(row, "account_strength")?,
        ranged: table.int(row, "account_ranged")?,
        prayer: table.int(row, "account_prayer")?,
        base_speed: table.int(row, "weapon_attack_speed")?,
        base_range: table.int(row, "weapon_attack_range")?,
        style_ids: table.styles(row)?,
        attack_bonus: [
            table.int(row, "attack_stab")?,
            table.int(row, "attack_slash")?,
            table.int(row, "attack_crush")?,
            table.int(row, "attack_ranged")?,
        ],
        melee_strength: table.int(row, "melee_strength")?,
        ranged_strength: table.int(row, "ranged_strength")?,
    })
}

fn resolved_candidate(
    kernel: &CombatKernel<'_>,
    table: &MatrixTable,
    row_index: usize,
    items_by_id: &HashMap<i64, &EquipmentItem>,
    rolls: &DefenceRolls,
) -> Result<(ReductionCandidate, ResolvedSource)> {
    let row = &table.rows[row_index];
    let static_candidate = static_candidate(table, row, items_by_id)?;
    let styles = kernel.resolve_styles(&style_inputs(table, row)?)?;
    let defence_level = table.int(row, "account_defence")?;
    let mut metrics: BTreeMap<String, i64> = BTreeMap::new();
    for style in &styles {
        let prefix = format!("style:{}", style.style_id);
        metrics.insert(format!("{prefix}:attack_roll"), style.attack_roll);
        metrics.insert(format!("{prefix}:max_hit"), style.max_hit);
        metrics.insert(format!("{prefix}:potted_max_hit"), style.potted_max_hit);
        metrics.insert(format!("{prefix}:cooldown_quality"), -style.cooldown_ticks);
        metrics.insert(format!("{prefix}:maximum_range"), style.maximum_range);
        for damage_type in DEFENCE_TYPES {
            let bonus = table.int(row, &format!("defence_{damage_type}"))?;
            metrics.insert(
                format!("{prefix}:defence_roll:{damage_type}"),
                rolls.get(defence_level, bonus, style.defence_style_bonus),
            );
        }
    }
    metrics.insert("magic_attack_bonus".into(), table.int(row, "attack_magic")?);
    metrics.insert("magic_defence_bonus".into(), table.int(row, "defence_magic")?);
    metrics.insert("magic_damage_percent".into(), table.int(row, "magic_damage")?);
    metrics.insert("prayer_bonus".into(), table.int(row, "prayer")?);
    metrics.insert("hitpoints".into(), table.int(row, "account_hitpoints")?);
    metrics.insert("prayer_level".into(), table.int(row, "account_prayer")?);
    let metrics: Vec<(String, i64)> = metrics.into_iter().collect();
    let signature = canonical_hash(&json!({
        "comparison_class": static_candidate.class.frozen_document(),
        "resolved_metrics": metrics.iter().map(|(k, v)| json!([k, v])).collect::<Vec<_>>(),
        "capabilities": static_candidate.capabilities,
    }));
    let candidate = ReductionCandidate {
        candidate_id: static_candidate.candidate_id.clone(),
        equivalence_signature: signature.clone(),
        comparison_class: static_candidate.class,
        metrics,
        capabilities: static_candidate.capabilities,
    };
    let source = ResolvedSource {
        row_index,
        signature,
        styles,
        best_expected_damage_per_tick: BTreeMap::new(),
        cadence_ko_probabilities: BTreeMap::new(),
    };
    Ok((candidate, source))
}

/// Cadence cache key: what the summary actually depends on per style.
type CadenceKey = Vec<(String, i64, i64, i64)>;

/// `(best_expected_damage_per_tick, cadence_ko_probabilities)` shared by every survivor with one cadence key.
type CadenceSummary = (BTreeMap<String, Rational>, BTreeMap<String, Rational>);

fn cadence_key(styles: &[ResolvedStyle]) -> CadenceKey {
    styles
        .iter()
        .map(|s| (s.damage_type.clone(), s.attack_roll, s.max_hit, s.cooldown_ticks))
        .collect()
}

fn cadence_summary(kernel: &CombatKernel<'_>, key: &CadenceKey, rolls: &RepresentativeRolls) -> Result<CadenceSummary> {
    let mut best_dpt = BTreeMap::new();
    let mut ko = BTreeMap::new();
    for label in LABELS {
        let label_rolls = &rolls[label];
        let mut distributions = Vec::with_capacity(key.len());
        for (damage_type, attack_roll, max_hit, cooldown) in key {
            let chance = kernel.accuracy(*attack_roll, label_rolls[damage_type])?;
            distributions.push((*cooldown, DamageDistribution::from_success_chance(&chance, *max_hit, kernel.zero_to_one)));
        }
        let best = distributions
            .iter()
            .map(|(cooldown, d)| d.expected_damage() / Rational::int(*cooldown as i128))
            .max()
            .ok_or_else(|| anyhow!("Gear matrix weapon has no resolved styles"))?;
        best_dpt.insert(label.to_owned(), best);
        for window in WINDOWS {
            let mut best_by_hp: Vec<Rational> = HP_THRESHOLDS.iter().map(|_| Rational::zero()).collect();
            for (cooldown, distribution) in &distributions {
                let attacks = 1 + (window - 1) / cooldown;
                let mut total = DamageDistribution::certain(0);
                for _ in 0..attacks {
                    total = total.convolve(distribution);
                }
                for (slot, hp) in HP_THRESHOLDS.iter().enumerate() {
                    let value = total.at_least(*hp);
                    if value > best_by_hp[slot] {
                        best_by_hp[slot] = value;
                    }
                }
            }
            for (slot, hp) in HP_THRESHOLDS.iter().enumerate() {
                ko.insert(format!("{label}:{window}:{hp}"), best_by_hp[slot].clone());
            }
        }
    }
    Ok((best_dpt, ko))
}

fn account_profile_scope(table: &MatrixTable) -> Result<&'static str> {
    for row in &table.rows {
        for skill in BAND_SKILLS {
            let (min, max, account) = (
                table.get(row, &format!("{skill}_min"))?,
                table.get(row, &format!("{skill}_max"))?,
                table.get(row, &format!("account_{skill}"))?,
            );
            if min != max || max != account {
                return Ok(BAND_ACCOUNT_SCOPE);
            }
        }
    }
    Ok(EXACT_ACCOUNT_SCOPE)
}

pub fn screen_resolved_gear_matrix<'t>(
    kernel: &CombatKernel<'_>,
    items: &[EquipmentItem],
    table: &'t MatrixTable,
    input_path: &str,
    audit_limit: usize,
) -> Result<ResolvedScreenReport<'t>> {
    let items_by_id: HashMap<i64, &EquipmentItem> = items.iter().map(|item| (item.item_id, item)).collect();
    let rolls = DefenceRolls::build(kernel, table)?;
    let representative = representative_rolls(kernel, table, &rolls)?;
    let resolved: Vec<(ReductionCandidate, ResolvedSource)> = (0..table.rows.len())
        .into_par_iter()
        .map(|index| resolved_candidate(kernel, table, index, &items_by_id, &rolls))
        .collect::<Result<_>>()?;
    let mut candidates = Vec::with_capacity(resolved.len());
    let mut sources: HashMap<String, ResolvedSource> = HashMap::with_capacity(resolved.len());
    for (candidate, source) in resolved {
        if sources.insert(candidate.candidate_id.clone(), source).is_some() {
            bail!("Gear matrix contains duplicate structural candidate {}", candidate.candidate_id);
        }
        candidates.push(candidate);
    }
    let reduction = reduce_candidates(candidates);
    let keys: HashSet<CadenceKey> = reduction
        .retained_candidates
        .iter()
        .map(|c| cadence_key(&sources[&c.candidate_id].styles))
        .collect();
    let summaries: HashMap<CadenceKey, CadenceSummary> = keys
        .into_par_iter()
        .map(|key| cadence_summary(kernel, &key, &representative).map(|summary| (key, summary)))
        .collect::<Result<_>>()?;
    for retained in &reduction.retained_candidates {
        let source = sources.get_mut(&retained.candidate_id).expect("retained candidate has a source");
        let (best_dpt, ko) = &summaries[&cadence_key(&source.styles)];
        source.best_expected_damage_per_tick = best_dpt.clone();
        source.cadence_ko_probabilities = ko.clone();
    }
    Ok(ResolvedScreenReport {
        input_path: input_path.to_owned(),
        table,
        reduction,
        representative_rolls: representative,
        sources,
        audit_limit,
        account_profile_scope: account_profile_scope(table)?,
    })
}

fn styles_json(styles: &[ResolvedStyle]) -> String {
    let value: Vec<Value> = styles
        .iter()
        .map(|s| {
            json!({
                "style_id": s.style_id,
                "damage_type": s.damage_type,
                "attack_roll": s.attack_roll,
                "max_hit": s.max_hit,
                "potted_max_hit": s.potted_max_hit,
                "cooldown_ticks": s.cooldown_ticks,
                "maximum_range": s.maximum_range,
            })
        })
        .collect();
    canonical_json(&Value::Array(value))
}

pub fn fraction_map_json(values: &BTreeMap<String, Rational>) -> String {
    let map: serde_json::Map<String, Value> = values.iter().map(|(k, v)| (k.clone(), fraction_document(v))).collect();
    canonical_json(&Value::Object(map))
}

pub const MANIFEST_COLUMNS: [&str; 6] = [
    "candidate_id",
    "resolved_signature",
    "resolved_styles_json",
    "best_expected_damage_per_tick_json",
    "cadence_ko_probabilities_json",
    "cadence_ko_scope",
];

pub fn write_survivor_manifest(report: &ResolvedScreenReport<'_>, output: &Path) -> Result<()> {
    let mut writer = csv_writer(output)?;
    let mut header: Vec<&str> = MANIFEST_COLUMNS.to_vec();
    header.extend(report.table.headers.iter().map(String::as_str));
    writer.write_record(&header)?;
    let mut ids: Vec<&str> = report.reduction.retained_candidates.iter().map(|c| c.candidate_id.as_str()).collect();
    ids.sort_unstable();
    for candidate_id in ids {
        let source = &report.sources[candidate_id];
        let mut record: Vec<String> = vec![
            candidate_id.to_owned(),
            source.signature.clone(),
            styles_json(&source.styles),
            fraction_map_json(&source.best_expected_damage_per_tick),
            fraction_map_json(&source.cadence_ko_probabilities),
            CADENCE_SCOPE.to_owned(),
        ];
        record.extend(report.table.rows[source.row_index].iter().map(str::to_owned));
        writer.write_record(&record)?;
    }
    writer.flush()?;
    Ok(())
}

pub fn report_document(report: &ResolvedScreenReport<'_>) -> Value {
    let mut counts = report.reduction.counts.to_document();
    counts.insert("remaining_resolved_options".into(), json!(report.reduction.counts.remaining_pareto_candidates));
    let limit = report.audit_limit;
    json!({
        "scope": "resolved_single_weapon_gear_envelope_v1",
        "input": report.input_path,
        "verification": {
            "status": "verified_for_resolved_single_weapon_dominance",
            "production_ready": false,
            "perfect_play_claim": false,
            "account_profile_scope": report.account_profile_scope,
            "weapon_scope": "one equipped weapon per row; primary/KO weapon-pair expansion is not included",
            "dominance_proof": "exact attack rolls, max-hit floors, cooldown/range, per-style defence rolls, HP/Prayer, and preserved magic/prayer dimensions",
            "window_scope": "cadence-only repeated-weapon PMFs; representative KO metrics are reported but are not the sole dominance proof",
        },
        "counts": counts,
        "windows": WINDOWS,
        "hp_thresholds": HP_THRESHOLDS,
        "representative_defence_rolls": report.representative_rolls,
        "manifest_candidate_count": report.reduction.retained_candidates.len(),
        "audit_examples": {
            "exact_duplicates": report.reduction.exact_duplicate_audits.iter().take(limit).map(|a| a.to_document()).collect::<Vec<_>>(),
            "dominance": report.reduction.dominance_audits.iter().take(limit).map(|a| a.to_document()).collect::<Vec<_>>(),
        },
    })
}

pub fn write_report(report: &ResolvedScreenReport<'_>, output: &Path) -> Result<()> {
    write_json(output, &report_document(report))
}

pub fn load_table(path: &Path) -> Result<MatrixTable> {
    MatrixTable::read(path, &required_columns())
}
