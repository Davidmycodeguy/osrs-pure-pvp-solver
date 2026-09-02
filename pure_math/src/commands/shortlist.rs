//! `shortlist-survivors <ruleset> <manifest.csv> --output=.. [--max-builds=0]`
//!
//! Writes the survivor rows Stage 5 would keep under `--max-builds` (top-N union by medium-defence
//! DPT, by Strength then potted max hit, and by physical defence; 0 keeps every row) as a smaller
//! manifest, so Stage 4 and Stage 5 can run on the same bounded population.

use std::collections::HashSet;

use anyhow::{anyhow, Result};
use serde_json::json;

use super::screen::python_path_string;
use crate::cli::Args;
use crate::combat::CombatKernel;
use crate::io::csv_writer;
use crate::kits::scores::shortlist_builds;
use crate::mechanics::MechanicRegistry;
use crate::ranking::load::load_ranking_candidates;

pub fn run(args: &Args) -> Result<()> {
    let ruleset = args.path(1, "ruleset")?;
    let input = args.positional(2, "input")?;
    let output = args.flag("output").ok_or_else(|| anyhow!("--output is required"))?;
    let max_builds = usize::try_from(args.flag_int("max-builds", 0)?).map_err(|_| anyhow!("--max-builds cannot be negative"))?;
    let mechanics = MechanicRegistry::load(&ruleset.join("mechanics.json"))?;
    let kernel = CombatKernel::new(&mechanics)?;
    let loaded = load_ranking_candidates(std::path::Path::new(input), &kernel)?;
    let total = loaded.candidates.len();
    let kept: HashSet<String> = shortlist_builds(loaded.candidates, max_builds).into_iter().map(|c| c.candidate_id).collect();
    let mut reader = csv::Reader::from_path(input)?;
    let headers = reader.headers()?.clone();
    let id_index = headers
        .iter()
        .position(|h| h == "candidate_id")
        .ok_or_else(|| anyhow!("manifest has no candidate_id column"))?;
    let mut writer = csv_writer(std::path::Path::new(output))?;
    writer.write_record(&headers)?;
    let mut written = 0usize;
    for record in reader.records() {
        let record = record?;
        if kept.contains(&record[id_index]) {
            writer.write_record(&record)?;
            written += 1;
        }
    }
    writer.flush()?;
    println!(
        "{}",
        crate::canonical::pretty_sorted_json(&json!({
            "input": python_path_string(input),
            "output": python_path_string(output),
            "survivors": total,
            "kept": written,
            "max_builds": max_builds,
        }))
    );
    Ok(())
}
