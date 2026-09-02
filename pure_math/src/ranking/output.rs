//! Ranked CSV (with the source manifest columns joined on) and the ranking
//! report JSON, in the exact layouts `survivor_ranking` wrote.

use std::path::Path;

use anyhow::Result;
use serde_json::{json, Map, Value};

use super::{RankedCandidate, SurvivorRankingReport, DAMAGE_TYPES, DEFENCE_STATES, LEVEL_NAMES, WINDOWS};
use crate::canonical::fraction_document;
use crate::io::{csv_writer, write_json};
use crate::rational::Rational;

pub const RANKED_FIELDS: [&str; 59] = [
    "rank",
    "tier",
    "candidate_id",
    "resolved_signature",
    "overall_score",
    "overall_score_decimal",
    "sustain_score",
    "race_score",
    "burst_score",
    "defence_score",
    "utility_score",
    "race_penalty3_worst_fish",
    "race_penalty3_p10_fish",
    "race_penalty3_mean_fish",
    "race_penalty0_worst_fish",
    "race_penalty0_mean_fish",
    "dpt_low",
    "dpt_medium",
    "dpt_high",
    "ko_4_tick",
    "ko_5_tick",
    "ko_8_tick",
    "ko_12_tick",
    "maximum_attack_roll",
    "max_hit",
    "potted_max_hit",
    "maximum_range",
    "defence_stab_roll",
    "defence_slash_roll",
    "defence_crush_roll",
    "defence_ranged_roll",
    "magic_attack_bonus",
    "magic_defence_bonus",
    "prayer_bonus",
    "niche_flags",
    "rank_reasons",
    "simulator_seed",
    "simulator_seed_reasons",
    "profile_id",
    "account_attack",
    "account_strength",
    "account_ranged",
    "account_magic",
    "account_prayer",
    "account_defence",
    "account_hitpoints",
    "head_name",
    "neck_name",
    "body_name",
    "legs_name",
    "hands_name",
    "weapon_name",
    "ammo_name",
    "shield_name",
    "weapon_type",
    "weapon_slot",
    "two_handed",
    "damage_types",
    "style_ids",
];

/// `f"{n}/{d}"`, always with the denominator (unlike `Display`).
pub fn fraction_text(value: &Rational) -> String {
    format!("{}/{}", value.numerator(), value.denominator())
}

fn python_bool(flag: bool) -> &'static str {
    if flag {
        "True"
    } else {
        "False"
    }
}

/// Python `f"{float(x):.8f}"`.
fn decimal_text(value: &Rational) -> String {
    format!("{:.8}", value.to_f64())
}

fn ranked_record(report: &SurvivorRankingReport, ranked: &RankedCandidate) -> Vec<String> {
    let candidate = &report.candidates[ranked.index];
    let primary = ranked.race_scenarios.iter().find(|s| s.eat_penalty == 3).unwrap_or(&ranked.race_scenarios[0]);
    let sensitivity = ranked.race_scenarios.iter().find(|s| s.eat_penalty == 0).unwrap_or(primary);
    let mut record: Vec<String> = vec![
        ranked.rank.to_string(),
        ranked.tier.to_owned(),
        candidate.candidate_id.clone(),
        candidate.resolved_signature.clone(),
        fraction_text(&ranked.overall_score),
        decimal_text(&ranked.overall_score),
    ];
    for category in ["sustain", "race", "burst", "defence", "utility"] {
        record.push(fraction_text(&ranked.category_scores[category]));
    }
    record.extend([
        fraction_text(&primary.worst_margin_fish),
        fraction_text(&primary.tenth_percentile_margin_fish),
        fraction_text(&primary.mean_margin_fish),
        fraction_text(&sensitivity.worst_margin_fish),
        fraction_text(&sensitivity.mean_margin_fish),
    ]);
    record.extend(candidate.sustained_dpt.iter().map(fraction_text));
    record.extend(candidate.ko_by_window.iter().map(fraction_text));
    record.extend(
        [
            candidate.maximum_attack_roll,
            candidate.max_hit,
            candidate.potted_max_hit,
            candidate.maximum_range,
        ]
        .map(|v| v.to_string()),
    );
    record.extend(candidate.defence_rolls.map(|v| v.to_string()));
    record.extend([candidate.magic_attack_bonus, candidate.magic_defence_bonus, candidate.prayer_bonus].map(|v| v.to_string()));
    record.extend([
        ranked.niche_flags.join(";"),
        ranked.rank_reasons.join(";"),
        python_bool(!ranked.simulator_seed_reasons.is_empty()).to_owned(),
        ranked.simulator_seed_reasons.join(";"),
        candidate.profile_id.to_string(),
    ]);
    record.extend(candidate.levels.map(|v| v.to_string()));
    record.extend(candidate.equipment_names.iter().cloned());
    record.extend([
        candidate.weapon_type.clone(),
        candidate.weapon_slot.clone(),
        python_bool(candidate.two_handed).to_owned(),
        candidate.damage_types.join(";"),
        candidate.styles.iter().map(|s| s.style_id.as_str()).collect::<Vec<_>>().join(";"),
    ]);
    debug_assert_eq!(record.len(), RANKED_FIELDS.len());
    record.extend(candidate.source_values.iter().cloned());
    record
}

/// Ranked rows in rank order, followed by every remaining manifest column.
pub fn write_ranked_survivors_csv(report: &SurvivorRankingReport, output: &Path) -> Result<()> {
    let mut writer = csv_writer(output)?;
    let mut header: Vec<&str> = RANKED_FIELDS.to_vec();
    header.extend(report.source_fields.iter().map(String::as_str));
    writer.write_record(&header)?;
    for ranked in &report.rankings {
        writer.write_record(ranked_record(report, ranked))?;
    }
    writer.flush()?;
    Ok(())
}

fn ranked_document(report: &SurvivorRankingReport, ranked: &RankedCandidate) -> Value {
    let candidate = &report.candidates[ranked.index];
    let fraction_map = |pairs: Vec<(String, &Rational)>| -> Value { Value::Object(pairs.into_iter().map(|(k, v)| (k, fraction_document(v))).collect()) };
    json!({
        "rank": ranked.rank,
        "tier": ranked.tier,
        "candidate_id": candidate.candidate_id,
        "resolved_signature": candidate.resolved_signature,
        "overall_score": fraction_document(&ranked.overall_score),
        "category_scores": fraction_map(ranked.category_scores.iter().map(|(k, v)| (k.to_string(), v)).collect()),
        "race_scenarios": ranked.race_scenarios.iter().map(|scenario| json!({
            "eat_penalty": scenario.eat_penalty,
            "opponent_count": scenario.opponent_count,
            "worst_margin_fish": fraction_document(&scenario.worst_margin_fish),
            "tenth_percentile_margin_fish": fraction_document(&scenario.tenth_percentile_margin_fish),
            "mean_margin_fish": fraction_document(&scenario.mean_margin_fish),
            "win_fraction": fraction_document(&scenario.win_fraction),
        })).collect::<Vec<_>>(),
        "sustained_dpt": fraction_map(DEFENCE_STATES.iter().zip(&candidate.sustained_dpt).map(|(k, v)| (k.to_string(), v)).collect()),
        "cadence_ko_by_window": fraction_map(WINDOWS.iter().zip(&candidate.ko_by_window).map(|(k, v)| (k.to_string(), v)).collect()),
        "resolved_styles": candidate.styles.iter().map(|style| json!({
            "style_id": style.style_id,
            "damage_type": style.damage_type,
            "attack_roll": style.attack_roll,
            "max_hit": style.max_hit,
            "potted_max_hit": style.potted_max_hit,
            "cooldown_ticks": style.cooldown_ticks,
            "maximum_range": style.maximum_range,
        })).collect::<Vec<_>>(),
        "maximum_attack_roll": candidate.maximum_attack_roll,
        "max_hit": candidate.max_hit,
        "potted_max_hit": candidate.potted_max_hit,
        "maximum_range": candidate.maximum_range,
        "defence_rolls": DAMAGE_TYPES.iter().zip(candidate.defence_rolls).map(|(k, v)| (k.to_string(), json!(v))).collect::<Map<_, _>>(),
        "niche_flags": ranked.niche_flags,
        "rank_reasons": ranked.rank_reasons,
        "simulator_seed_reasons": ranked.simulator_seed_reasons,
        "profile_id": candidate.profile_id,
        "levels": LEVEL_NAMES.iter().zip(candidate.levels).map(|(k, v)| (k.to_string(), json!(v))).collect::<Map<_, _>>(),
        "weapon": {
            "name": candidate.weapon_name,
            "type": candidate.weapon_type,
            "slot": candidate.weapon_slot,
            "two_handed": candidate.two_handed,
        },
        "equipment_names": candidate.equipment_names,
    })
}

pub fn report_document(report: &SurvivorRankingReport) -> Value {
    let panel_count = report.panel_candidate_ids.len();
    json!({
        "scope": "resolved_single_weapon_candidate_priority_ranking_v1",
        "input": report.input_path,
        "verification": {
            "status": "heuristic_priority_order_only",
            "production_ready": false,
            "perfect_play_claim": false,
            "deletes_candidates": false,
            "candidate_scope": "resolved single-equipped-weapon gear-unlock representatives; not complete combat-level-30 accounts",
            "combat_scope": "stationary cadence damage plus a notional attrition race; no movement, projectile arrival alignment, weapon switching, spell damage, prayer activation, potion timing, or opponent policy",
            "inventory_scope": "equal notional food slots for every row; carried switches, runes, potions, and food composition are deferred to kit/simulator search",
            "authority": "the later mechanics-faithful simulator/RL solver remains final",
        },
        "counts": counts_document(report),
        "formula": {
            "successful_hit_expected_damage": "p_hit * (max_hit/2 + 1/(max_hit+1)) when PvP successful 0 becomes 1",
            "uptime": "heal_per_eat / (heal_per_eat + eat_penalty * incoming_dpt)",
            "race_margin": "signed extra survival ticks multiplied by the loser's effective dpt, reported in heal_per_eat units",
            "panel_self_matchups": "excluded; panel rows face one deterministic ranking-only reserve so every real candidate has the same number of distinct opponents",
            "category_scores": {
                "sustain": "mean population midrank percentile of low/medium/high exact DPT",
                "race": "mean percentile of robust worst, penalty-3 p10/mean, and penalty-0 mean margins",
                "burst": "mean percentile of 4/5/8/12-tick cadence KO, max hit, and potted max hit",
                "defence": "mean percentile of stab/slash/crush/ranged defence rolls and magic defence bonus",
                "utility": "mean percentile of range, style breadth, Prayer level/bonus, and magic attack bonus",
            },
            "overall_score": "equal-weight mean of sustain, race, burst, defence, and utility category percentiles",
            "tie_break": "race, burst, sustain, defence, utility, then candidate_id",
            "tiers": "S top 1%; A next to 5%; B next to 20%; N lower-ranked panel/extreme niche; C remainder",
        },
        "configuration": {
            "food_slots": report.config.food_slots,
            "heal_per_eat": report.config.heal_per_eat,
            "eat_penalties": report.config.eat_penalties,
            "panel_size": panel_count,
            "ranking_self_matchup_reserve_candidate_id": report.ranking_self_matchup_reserve_candidate_id,
        },
        "simulator_seed_panel": report.panel_candidate_ids.iter().map(|id| json!({
            "candidate_id": id,
            "selection_reasons": report.panel_reasons[id],
        })).collect::<Vec<_>>(),
        "top_preview": report.rankings.iter().take(report.config.preview_size).map(|r| ranked_document(report, r)).collect::<Vec<_>>(),
    })
}

/// `counts` section shared by the report and the CLI summary.
pub fn counts_document(report: &SurvivorRankingReport) -> Value {
    let n = report.rankings.len();
    let p = report.panel_candidate_ids.len();
    json!({
        "input_candidates": n,
        "ranked_candidates": n,
        "candidates_removed_by_ranking": 0,
        "recommended_initial_simulator_candidates": p,
        "cheap_envelope_panel_pairings": if n > p { n * p } else { n * n.saturating_sub(1).max(1) },
        "full_unordered_nonself_matchups": n * n.saturating_sub(1) / 2,
        "full_directed_nonself_matchups": n * n.saturating_sub(1),
        "full_directed_matrix_cells": n * n,
        "initial_panel_unordered_nonself_matchups": p * p.saturating_sub(1) / 2,
        "initial_panel_directed_nonself_matchups": p * p.saturating_sub(1),
        "initial_panel_directed_matrix_cells": p * p,
        "expensive_matchup_solves_run_by_this_command": 0,
        "tier_counts": report.tier_counts(),
    })
}

pub fn write_survivor_ranking_report(report: &SurvivorRankingReport, output: &Path) -> Result<()> {
    write_json(output, &report_document(report))
}
