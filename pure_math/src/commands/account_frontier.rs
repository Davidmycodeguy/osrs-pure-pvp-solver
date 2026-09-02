//! `account-frontier <ruleset> [--combat-level=30] [--defence-levels=1] [--ranking-output=..] [--full-output=..] [--report-output=..]`

use anyhow::Result;
use serde_json::{json, Value};

use crate::account_frontier::{build_account_frontier_with_defence, parse_defence_levels, AccountFrontier};
use crate::accounts::DEFENCE_LEVEL;
use crate::cli::Args;
use crate::io::{write_account_csv, write_json};
use crate::mechanics::MechanicRegistry;

pub fn frontier_document(frontier: &AccountFrontier) -> Value {
    json!({
        "combat_level": frontier.combat_level,
        "counts": {
            "full_frontier": frontier.full_frontier.len(),
            "ranking_frontier": frontier.ranking_frontier.len(),
            "raw_legal_states": frontier.raw_count,
        },
        "defence_level": if frontier.defence_levels == [DEFENCE_LEVEL] { serde_json::json!(DEFENCE_LEVEL) } else { serde_json::json!(frontier.defence_levels) },
        "full_frontier_scope": "Pareto over all six trainable skills; Magic preserved as a dimension",
        "hitpoints_model": "standard_f2p_training_reachable_range",
        "magic_model": "maximum_level_preserving_combat_level",
        "prayer_levels": frontier.prayer_levels,
        "purpose": "exact_combat_level_account_frontier",
        "ranking_frontier_scope": "Pareto over Attack/Strength/Ranged/Prayer/Hitpoints; Magic treated as leftover fill",
        "schema_version": 1,
    })
}

pub fn run(args: &Args) -> Result<()> {
    let ruleset = args.path(1, "ruleset")?;
    let mechanics = MechanicRegistry::load(&ruleset.join("mechanics.json"))?;
    let combat_level = args.flag_int("combat-level", 30)?;
    let ranking_output = args.flag_path("ranking-output", "outputs/cb30/accounts-ranking.csv");
    let full_output = args.flag_path("full-output", "outputs/cb30/accounts-full.csv");
    let report_output = args.flag_path("report-output", "outputs/cb30/account-frontier.json");

    let defence_levels = parse_defence_levels(args.flag("defence-levels").unwrap_or("1"))?;
    let frontier = build_account_frontier_with_defence(&mechanics, combat_level, &defence_levels)?;
    write_account_csv(&frontier.ranking_frontier, &mechanics, &ranking_output)?;
    write_account_csv(&frontier.full_frontier, &mechanics, &full_output)?;
    let document = frontier_document(&frontier);
    write_json(&report_output, &document)?;
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "full_frontier": frontier.full_frontier.len(),
            "full_output": full_output.display().to_string(),
            "ranking_frontier": frontier.ranking_frontier.len(),
            "ranking_output": ranking_output.display().to_string(),
            "raw_legal_states": frontier.raw_count,
            "report_output": report_output.display().to_string(),
        }))?
    );
    Ok(())
}
