//! `rank-resolved-survivors <ruleset> <manifest.csv> --ranked-output=.. --report-output=..
//!   [--panel-size=32] [--food-slots=28] [--heal-per-eat=14] [--eat-penalties=3,0] [--preview-size=50]`

use anyhow::{anyhow, Result};
use serde_json::{json, Value};

use super::screen::python_path_string;
use crate::cli::Args;
use crate::combat::CombatKernel;
use crate::mechanics::MechanicRegistry;
use crate::ranking::output::{counts_document, write_ranked_survivors_csv, write_survivor_ranking_report};
use crate::ranking::scores::rank_survivor_manifest;
use crate::ranking::{RankingConfig, DEFAULT_EAT_PENALTIES};

fn eat_penalties(args: &Args) -> Result<Vec<i64>> {
    match args.flag("eat-penalties") {
        None => Ok(DEFAULT_EAT_PENALTIES.to_vec()),
        Some(text) => text
            .split([',', ' '])
            .filter(|s| !s.is_empty())
            .map(|s| s.parse::<i64>().map_err(|_| anyhow!("--eat-penalties must be integers, got {s:?}")))
            .collect(),
    }
}

fn config(args: &Args) -> Result<RankingConfig> {
    let non_negative = |name: &str, default: i64| -> Result<usize> {
        let value = args.flag_int(name, default)?;
        usize::try_from(value).map_err(|_| anyhow!("--{name} cannot be negative"))
    };
    Ok(RankingConfig {
        panel_size: non_negative("panel-size", 32)?,
        food_slots: args.flag_int("food-slots", 28)?,
        heal_per_eat: args.flag_int("heal-per-eat", 14)?,
        eat_penalties: eat_penalties(args)?,
        preview_size: non_negative("preview-size", 50)?,
    })
}

pub fn run(args: &Args) -> Result<()> {
    let ruleset = args.path(1, "ruleset")?;
    let input = args.positional(2, "input")?;
    let ranked_output = args.flag("ranked-output").ok_or_else(|| anyhow!("--ranked-output is required"))?;
    let report_output = args.flag("report-output").ok_or_else(|| anyhow!("--report-output is required"))?;
    let config = config(args)?;
    let mechanics = MechanicRegistry::load(&ruleset.join("mechanics.json"))?;
    let kernel = CombatKernel::new(&mechanics)?;
    let report = rank_survivor_manifest(std::path::Path::new(input), &python_path_string(input), &kernel, &config)?;
    write_ranked_survivors_csv(&report, std::path::Path::new(ranked_output))?;
    write_survivor_ranking_report(&report, std::path::Path::new(report_output))?;
    let mut summary = match counts_document(&report) {
        Value::Object(map) => map,
        _ => unreachable!("counts document is an object"),
    };
    summary.insert("input".into(), json!(python_path_string(input)));
    summary.insert("ranked_output".into(), json!(python_path_string(ranked_output)));
    summary.insert("report_output".into(), json!(python_path_string(report_output)));
    println!("{}", crate::canonical::pretty_sorted_json(&Value::Object(summary)));
    Ok(())
}
