//! `kits.csv` (rank order, kit + primary descriptive fields, no manifest
//! source columns) and the kit ranking report JSON.

use std::path::Path;

use anyhow::Result;
use serde_json::{json, Map, Value};

use super::{Kit, KitRankingReport, RankedKit, CATEGORIES, FINISH_THRESHOLDS, STACK_SCOPE, SWITCH_CADENCE_SCOPE};
use crate::canonical::fraction_document;
use crate::io::{csv_writer, write_json};
use crate::ranking::output::fraction_text;
use crate::ranking::{RankingCandidate, DAMAGE_TYPES, DEFENCE_STATES, HP_THRESHOLDS, LEVEL_NAMES, WINDOWS};
use crate::rational::Rational;

pub const KIT_FIELDS: [&str; 96] = [
    "rank",
    "tier",
    "kit_id",
    "candidate_id",
    "resolved_signature",
    "is_baseline",
    "ko_weapon_id",
    "ko_weapon_name",
    "ko_damage_types",
    "ko_style_ids",
    "ko_max_hit",
    "ko_potted_max_hit",
    "ko_attack_roll",
    "ko_cooldown_ticks",
    "switch_slots",
    "food_slots",
    "overall_score",
    "overall_score_decimal",
    "sustain_score",
    "race_score",
    "burst_score",
    "defence_score",
    "utility_score",
    "ko_switch_score",
    "race_penalty3_worst_fish",
    "race_penalty3_p10_fish",
    "race_penalty3_mean_fish",
    "race_penalty0_worst_fish",
    "race_penalty0_mean_fish",
    "stack_ko_5",
    "stack_ko_10",
    "stack_ko_15",
    "stack_ko_20",
    "stack_ko_25",
    "stack_ko_30",
    "switch_ko_4_tick",
    "switch_ko_5_tick",
    "switch_ko_8_tick",
    "switch_ko_12_tick",
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
    "kill_pressure",
    "kill_bite",
    "finish_10",
    "finish_15",
    "finish_20",
    "pressure_rank",
    "strength_potions",
    "max_burst",
    "ko_neck_id",
    "ko_neck_name",
    "spell_name",
    "spell_max_hit",
    "spell_attack_roll",
    "rune_slots",
];

fn python_bool(flag: bool) -> &'static str {
    if flag {
        "True"
    } else {
        "False"
    }
}

fn decimal_text(value: &Rational) -> String {
    format!("{:.8}", value.to_f64())
}

struct KoSummary {
    weapon_id: String,
    weapon_name: String,
    damage_types: String,
    style_ids: String,
    max_hit: i64,
    potted_max_hit: i64,
    attack_roll: i64,
    cooldown_ticks: i64,
    switch_slots: i64,
}

fn ko_summary(kit: &Kit, primary: &RankingCandidate) -> KoSummary {
    let styles = kit.ko_styles(primary);
    let mut damage_types: Vec<&str> = styles.iter().map(|s| s.damage_type.as_str()).collect();
    damage_types.sort_unstable();
    damage_types.dedup();
    let (weapon_id, weapon_name, switch_slots) = match &kit.ko {
        Some(ko) => (ko.weapon_id.to_string(), ko.weapon_name.clone(), ko.switch_slots),
        None => (String::new(), primary.weapon_name.clone(), 0),
    };
    KoSummary {
        weapon_id,
        weapon_name,
        damage_types: damage_types.join(";"),
        style_ids: styles.iter().map(|s| s.style_id.as_str()).collect::<Vec<_>>().join(";"),
        max_hit: styles.iter().map(|s| s.max_hit).max().unwrap_or(0),
        potted_max_hit: styles.iter().map(|s| s.potted_max_hit).max().unwrap_or(0),
        attack_roll: styles.iter().map(|s| s.attack_roll).max().unwrap_or(0),
        cooldown_ticks: styles.iter().map(|s| s.cooldown_ticks).min().unwrap_or(0),
        switch_slots,
    }
}

fn record(report: &KitRankingReport, ranked: &RankedKit) -> Vec<String> {
    let kit = &report.kits[ranked.index];
    let ko = &report.ko_metrics[ranked.index];
    let primary = &report.candidates[kit.primary];
    let summary = ko_summary(kit, primary);
    let penalty3 = ranked.race_scenarios.iter().find(|s| s.eat_penalty == 3).unwrap_or(&ranked.race_scenarios[0]);
    let penalty0 = ranked.race_scenarios.iter().find(|s| s.eat_penalty == 0).unwrap_or(penalty3);
    let mut out: Vec<String> = vec![
        ranked.rank.to_string(),
        ranked.tier.to_owned(),
        kit.kit_id.clone(),
        primary.candidate_id.clone(),
        primary.resolved_signature.clone(),
        python_bool(kit.is_baseline()).to_owned(),
        summary.weapon_id,
        summary.weapon_name,
        summary.damage_types,
        summary.style_ids,
        summary.max_hit.to_string(),
        summary.potted_max_hit.to_string(),
        summary.attack_roll.to_string(),
        summary.cooldown_ticks.to_string(),
        summary.switch_slots.to_string(),
        kit.food_slots.to_string(),
        fraction_text(&ranked.overall_score),
        decimal_text(&ranked.overall_score),
    ];
    out.extend(CATEGORIES.iter().map(|c| fraction_text(&ranked.category_scores[c])));
    out.extend([
        fraction_text(&penalty3.worst_margin_fish),
        fraction_text(&penalty3.tenth_percentile_margin_fish),
        fraction_text(&penalty3.mean_margin_fish),
        fraction_text(&penalty0.worst_margin_fish),
        fraction_text(&penalty0.mean_margin_fish),
    ]);
    out.extend(ko.stack_by_hp.iter().map(fraction_text));
    out.extend(ko.switch_by_window.iter().map(fraction_text));
    out.extend(primary.sustained_dpt.iter().map(fraction_text));
    out.extend(primary.ko_by_window.iter().map(fraction_text));
    out.extend([primary.maximum_attack_roll, primary.max_hit, primary.potted_max_hit, primary.maximum_range].map(|v| v.to_string()));
    out.extend(primary.defence_rolls.map(|v| v.to_string()));
    out.extend([primary.magic_attack_bonus, primary.magic_defence_bonus, primary.prayer_bonus].map(|v| v.to_string()));
    out.extend([
        ranked.niche_flags.join(";"),
        ranked.rank_reasons.join(";"),
        python_bool(!ranked.simulator_seed_reasons.is_empty()).to_owned(),
        ranked.simulator_seed_reasons.join(";"),
        primary.profile_id.to_string(),
    ]);
    out.extend(primary.levels.map(|v| v.to_string()));
    out.extend(primary.equipment_names.iter().cloned());
    out.extend([
        primary.weapon_type.clone(),
        primary.weapon_slot.clone(),
        python_bool(primary.two_handed).to_owned(),
        primary.damage_types.join(";"),
        primary.styles.iter().map(|s| s.style_id.as_str()).collect::<Vec<_>>().join(";"),
    ]);
    out.extend([fraction_text(&ko.pressure), fraction_text(&ko.bite)]);
    out.extend(ko.finish.iter().map(fraction_text));
    out.push(ranked.pressure_rank.to_string());
    out.push(report.config.strength_potions.to_string());
    out.push(ko.max_burst.to_string());
    out.push(kit.ko.as_ref().and_then(|k| k.neck_id).map_or(String::new(), |id| id.to_string()));
    out.push(kit.ko.as_ref().and_then(|k| k.neck_name.clone()).unwrap_or_default());
    match &kit.spell {
        Some(spell) => out.extend([
            spell.name.clone(),
            spell.style.max_hit.to_string(),
            spell.style.attack_roll.to_string(),
            spell.rune_slots.to_string(),
        ]),
        None => out.extend([String::new(), "0".to_owned(), "0".to_owned(), "0".to_owned()]),
    }
    debug_assert_eq!(out.len(), KIT_FIELDS.len());
    out
}

pub fn write_kits_csv(report: &KitRankingReport, output: &Path) -> Result<()> {
    let mut writer = csv_writer(output)?;
    writer.write_record(KIT_FIELDS)?;
    for ranked in &report.rankings {
        writer.write_record(record(report, ranked))?;
    }
    writer.flush()?;
    Ok(())
}

fn fraction_map(pairs: impl Iterator<Item = (String, Rational)>) -> Value {
    Value::Object(pairs.map(|(k, v)| (k, fraction_document(&v))).collect())
}

fn ranked_document(report: &KitRankingReport, ranked: &RankedKit) -> Value {
    let kit = &report.kits[ranked.index];
    let ko = &report.ko_metrics[ranked.index];
    let tables = report.preview_tables.get(&ranked.index).expect("preview kits carry full KO tables");
    let primary = &report.candidates[kit.primary];
    let summary = ko_summary(kit, primary);
    json!({
        "rank": ranked.rank,
        "pressure_rank": ranked.pressure_rank,
        "tier": ranked.tier,
        "kit_id": kit.kit_id,
        "candidate_id": primary.candidate_id,
        "is_baseline": kit.is_baseline(),
        "kill_pressure": {
            "beats_one_heal": fraction_document(&ko.pressure),
            "expected_overshoot_hp": fraction_document(&ko.bite),
            "max_burst": ko.max_burst,
            "finish": fraction_map(FINISH_THRESHOLDS.iter().zip(&ko.finish).map(|(k, v)| (k.to_string(), v.clone()))),
        },
        "ko_weapon": {
            "id": kit.ko.as_ref().map(|k| k.weapon_id),
            "name": summary.weapon_name,
            "neck_id": kit.ko.as_ref().and_then(|k| k.neck_id),
            "neck_name": kit.ko.as_ref().and_then(|k| k.neck_name.clone()),
            "max_hit": summary.max_hit,
            "potted_max_hit": summary.potted_max_hit,
            "attack_roll": summary.attack_roll,
            "cooldown_ticks": summary.cooldown_ticks,
            "damage_types": summary.damage_types,
            "style_ids": summary.style_ids,
        },
        "switch_slots": summary.switch_slots,
        "food_slots": kit.food_slots,
        "spell": kit.spell.as_ref().map(|spell| json!({
            "name": spell.name,
            "max_hit": spell.style.max_hit,
            "attack_roll": spell.style.attack_roll,
            "cooldown_ticks": spell.style.cooldown_ticks,
            "rune_slots": spell.rune_slots,
        })),
        "overall_score": fraction_document(&ranked.overall_score),
        "category_scores": fraction_map(ranked.category_scores.iter().map(|(k, v)| (k.to_string(), v.clone()))),
        "race_scenarios": ranked.race_scenarios.iter().map(|s| json!({
            "eat_penalty": s.eat_penalty,
            "opponent_count": s.opponent_count,
            "worst_margin_fish": fraction_document(&s.worst_margin_fish),
            "tenth_percentile_margin_fish": fraction_document(&s.tenth_percentile_margin_fish),
            "mean_margin_fish": fraction_document(&s.mean_margin_fish),
            "win_fraction": fraction_document(&s.win_fraction),
        })).collect::<Vec<_>>(),
        "stack_ko": fraction_map(tables.stack.iter().map(|(k, v)| (k.clone(), v.clone()))),
        "stack_ko_by_hp": fraction_map(HP_THRESHOLDS.iter().zip(&ko.stack_by_hp).map(|(k, v)| (k.to_string(), v.clone()))),
        "switch_ko": fraction_map(tables.switch.iter().map(|(k, v)| (k.clone(), v.clone()))),
        "switch_ko_by_window": fraction_map(WINDOWS.iter().zip(&ko.switch_by_window).map(|(k, v)| (k.to_string(), v.clone()))),
        "sustained_dpt": fraction_map(DEFENCE_STATES.iter().zip(&primary.sustained_dpt).map(|(k, v)| (k.to_string(), v.clone()))),
        "cadence_ko_by_window": fraction_map(WINDOWS.iter().zip(&primary.ko_by_window).map(|(k, v)| (k.to_string(), v.clone()))),
        "defence_rolls": DAMAGE_TYPES.iter().zip(primary.defence_rolls).map(|(k, v)| (k.to_string(), json!(v))).collect::<Map<_, _>>(),
        "niche_flags": ranked.niche_flags,
        "rank_reasons": ranked.rank_reasons,
        "simulator_seed_reasons": ranked.simulator_seed_reasons,
        "profile_id": primary.profile_id,
        "levels": LEVEL_NAMES.iter().zip(primary.levels).map(|(k, v)| (k.to_string(), json!(v))).collect::<Map<_, _>>(),
        "primary_weapon": {
            "name": primary.weapon_name,
            "type": primary.weapon_type,
            "slot": primary.weapon_slot,
            "two_handed": primary.two_handed,
        },
        "equipment_names": primary.equipment_names,
    })
}

pub fn counts_document(report: &KitRankingReport) -> Value {
    let kits = report.kits.len();
    let baseline = report.kits.iter().filter(|k| k.is_baseline()).count();
    let with_option: std::collections::HashSet<usize> = report.kits.iter().filter(|k| !k.is_baseline()).map(|k| k.primary).collect();
    json!({
        "survivor_rows": report.candidates.len(),
        "kits": kits,
        "baseline_kits": baseline,
        "switch_kits": kits - baseline,
        "survivors_with_ko_option": with_option.len(),
        "panel_size": report.panel_candidate_ids.len(),
        "tier_counts": report.tier_counts(),
    })
}

pub fn report_document(report: &KitRankingReport) -> Value {
    json!({
        "scope": "ko_kit_priority_ranking_v1",
        "input": report.input_path,
        "screen_report": report.screen_report_path,
        "verification": {
            "status": "heuristic_priority_order_only",
            "production_ready": false,
            "perfect_play_claim": false,
            "deletes_candidates": false,
            "kit_scope": "one primary weapon plus at most one carried melee KO weapon that out-hits it; baseline no-switch kit kept for every survivor",
            "stack_scope": STACK_SCOPE,
            "switch_cadence_scope": SWITCH_CADENCE_SCOPE,
            "inventory_scope": "food_slots = inventory_slots - switch_slots - strength_potions - rune_slots; equipped ammo is free",
            "opponent_scope": "Stage 4 single-weapon panel with full inventory food; opponents do not switch",
            "not_modelled": ["movement", "distance", "projectile flight ticks", "PID order", "prayer", "shield defence loss on a 2H switch"],
            "authority": "the later mechanics-faithful simulator/RL solver remains final",
        },
        "counts": counts_document(report),
        "formula": {
            "stack_ko": "P(rapid shortbow arrow + one KO hit >= hp), max over KO styles, per representative defence state",
            "switch_cadence_ko": "max over primary style s and KO style k of P(s + k x n >= hp) with n = 1 + (window-1-cd_s) div cd_k when cd_s < window, also over every no-switch sequence",
            "race_outgoing": "best exact DPT over the union of primary and KO styles versus the opponent's defence roll",
            "race_food": "kit food_slots for the kit, inventory_slots for the opponent; margin as Stage 4",
            "category_scores": {
                "sustain": "mean population midrank percentile of low/medium/high exact DPT (primary)",
                "race": "mean percentile of robust worst, penalty-3 p10/mean, and penalty-0 mean margins (kit)",
                "burst": "mean percentile of 4/5/8/12-tick cadence KO, max hit, and potted max hit (primary)",
                "defence": "mean percentile of stab/slash/crush/ranged defence rolls and magic defence bonus (primary)",
                "utility": "mean percentile of range, style breadth, Prayer level/bonus, and magic attack bonus (primary)",
                "ko_switch": "mean percentile of stack KO mean, 4/5/8/12-tick switch KO, and KO max hit (kit)",
            },
            "overall_score": "equal-weight mean of the six category percentiles over the kit population",
            "tie_break": "race, ko_switch, burst, sustain, defence, utility, then kit_id",
            "kill_pressure": "P(best unanswerable burst > heal_per_eat): the arrow + KO stack for rapid shortbow kits, else the single hardest hit; kill_bite = E[max(burst - heal, 0)]; finish_h = P(burst >= h) for h in 10/15/20; all raw probabilities averaged over the three defence states, not percentiles",
            "strength_potion": "each carried potion costs one inventory slot (food_slots = inventory - switch_slots - potions); when >= 1, melee hits in the stack, switch-cadence and kill-pressure tables use the potted max hit (boost = 3 + floor(Strength/10)); the race keeps unpotted DPT; ranged and magic hits are unaffected",
            "max_burst": "highest possible unanswerable burst damage: arrow max hit + KO max hit for rapid-shortbow stack kits, else the hardest single hit; potted melee max when a Strength potion is carried",
            "amulet_switch": "each KO weapon is also tried with the worn amulet swapped for the legal amulet with the highest melee strength bonus (Amulet of strength); kept only when it raises the KO max hit; costs one more switch slot; kit_id includes ko_neck_id",
            "magic": "every kit also gets a runes variant carrying the hardest F2P spell the account can cast when its max hit beats the primary weapon; spells use magic.effective_attack (no boost, no style bonus, best F2P magic prayer), magic.attack_roll with the worn gear's magic attack bonus, magic.max_hit, 5-tick cast; cast bare-handed (no staves in the catalog) so each rune type costs one inventory slot; the spell joins the race DPT union, the switch-cadence windows as an opener, and the kill-pressure burst as a single hit (no magic-to-melee stack)",
            "magic.defence_roll_unverified": "opponent magic defence roll = (floor(0.7 x (Magic + 8)) + floor(0.3 x (Defence + 8))) x (magic defence bonus + 64); standard OSRS rule, not a verified ruleset mechanic; representative low/medium/high rolls are the 1/10, 1/2, 9/10 quantiles over the survivor population",
            "pressure_rank": "kits ordered by kill_pressure desc, then kill_bite desc, then penalty-3 mean race margin desc, then kit_id; reported alongside rank, not blended into it",
            "tiers": "S top 1%; A next to 5%; B next to 20%; N lower-ranked panel/extreme niche; C remainder",
        },
        "configuration": {
            "inventory_slots": report.config.inventory_slots,
            "strength_potions": report.config.strength_potions,
            "magic": report.config.magic,
            "heal_per_eat": report.config.heal_per_eat,
            "eat_penalties": report.config.eat_penalties,
            "panel_size": report.panel_candidate_ids.len(),
            "ranking_self_matchup_reserve_candidate_id": report.ranking_self_matchup_reserve_candidate_id,
        },
        "simulator_seed_panel": report.panel_candidate_ids.iter().map(|id| json!({
            "candidate_id": id,
            "selection_reasons": report.panel_reasons[id],
        })).collect::<Vec<_>>(),
        "top_preview": report.rankings.iter().take(report.config.preview_size).map(|r| ranked_document(report, r)).collect::<Vec<_>>(),
    })
}

pub fn write_kits_report(report: &KitRankingReport, output: &Path) -> Result<()> {
    write_json(output, &report_document(report))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn kit_fields_match_the_spec_order_and_have_no_duplicates() {
        assert_eq!(KIT_FIELDS[0], "rank");
        assert_eq!(KIT_FIELDS[2], "kit_id");
        assert_eq!(KIT_FIELDS[16], "overall_score");
        assert_eq!(KIT_FIELDS[23], "ko_switch_score");
        assert_eq!(KIT_FIELDS[29], "stack_ko_5");
        assert_eq!(KIT_FIELDS[35], "switch_ko_4_tick");
        assert_eq!(KIT_FIELDS[81], "style_ids");
        assert_eq!(KIT_FIELDS[82], "kill_pressure");
        assert_eq!(KIT_FIELDS[87], "pressure_rank");
        assert_eq!(KIT_FIELDS[88], "strength_potions");
        assert_eq!(KIT_FIELDS[89], "max_burst");
        assert_eq!(KIT_FIELDS[91], "ko_neck_name");
        assert_eq!(*KIT_FIELDS.last().unwrap(), "rune_slots");
        let unique: std::collections::HashSet<&str> = KIT_FIELDS.iter().copied().collect();
        assert_eq!(unique.len(), KIT_FIELDS.len());
    }
}
