//! `screen-resolved-gear-matrix <ruleset> <matrix.csv> [--manifest-output=..] [--report-output=..] [--audit-limit=20]`

use anyhow::Result;
use serde_json::json;

use crate::cli::Args;
use crate::combat::CombatKernel;
use crate::items::load_items;
use crate::mechanics::MechanicRegistry;
use crate::resolved_screen::{load_table, screen_resolved_gear_matrix, write_report, write_survivor_manifest};

/// Python's `str(Path(...))` on Windows uses backslashes; the report echoes it.
pub fn python_path_string(raw: &str) -> String {
    if cfg!(windows) {
        raw.replace('/', "\\")
    } else {
        raw.to_owned()
    }
}

pub fn run(args: &Args) -> Result<()> {
    let ruleset = args.path(1, "ruleset")?;
    let input = args.positional(2, "input")?;
    let manifest_output = args.flag_path("manifest-output", "outputs/cb30/resolved-survivors.csv");
    let report_output = args.flag_path("report-output", "outputs/cb30/resolved-screen-report.json");
    let audit_limit = args.flag_int("audit-limit", 20)?;
    anyhow::ensure!(audit_limit >= 0, "audit_limit cannot be negative");
    let mechanics = MechanicRegistry::load(&ruleset.join("mechanics.json"))?;
    let items = load_items(&ruleset.join("items.json"))?;
    let kernel = CombatKernel::new(&mechanics)?;
    let table = load_table(std::path::Path::new(input))?;
    let report = screen_resolved_gear_matrix(&kernel, &items, &table, &python_path_string(input), audit_limit as usize)?;
    write_survivor_manifest(&report, &manifest_output)?;
    write_report(&report, &report_output)?;
    let mut summary = report.reduction.counts.to_document();
    summary.insert("input".into(), json!(python_path_string(input)));
    summary.insert("manifest_output".into(), json!(manifest_output.display().to_string()));
    summary.insert("report_output".into(), json!(report_output.display().to_string()));
    summary.insert("remaining_resolved_options".into(), json!(report.reduction.counts.remaining_pareto_candidates));
    println!("{}", crate::canonical::pretty_sorted_json(&serde_json::Value::Object(summary)));
    Ok(())
}
