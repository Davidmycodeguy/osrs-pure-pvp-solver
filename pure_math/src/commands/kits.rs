//! `expand-ko-kits <ruleset> <manifest.csv> --screen-report=.. --kits-output=.. --report-output=..
//!   [--panel-size=32] [--inventory-slots=28] [--heal-per-eat=14] [--eat-penalties=3,0] [--preview-size=50]
//!   [--strength-potions=1] [--max-ko-options=0] [--max-builds=0] [--magic=1] [--threads=cores-2]`

use anyhow::{anyhow, Result};
use serde_json::{json, Value};

use super::screen::python_path_string;
use crate::cli::Args;
use crate::combat::CombatKernel;
use crate::items::load_items;
use crate::kits::output::{counts_document, write_kits_csv, write_kits_report};
use crate::kits::scores::rank_kits;
use crate::kits::KitConfig;
use crate::mechanics::MechanicRegistry;

fn eat_penalties(args: &Args) -> Result<Vec<i64>> {
    match args.flag("eat-penalties") {
        None => Ok(vec![3, 0]),
        Some(text) => text
            .split([',', ' '])
            .filter(|s| !s.is_empty())
            .map(|s| s.parse::<i64>().map_err(|_| anyhow!("--eat-penalties must be integers, got {s:?}")))
            .collect(),
    }
}

fn config(args: &Args) -> Result<KitConfig> {
    let non_negative = |name: &str, default: i64| -> Result<usize> {
        let value = args.flag_int(name, default)?;
        usize::try_from(value).map_err(|_| anyhow!("--{name} cannot be negative"))
    };
    Ok(KitConfig {
        panel_size: non_negative("panel-size", 32)?,
        inventory_slots: args.flag_int("inventory-slots", 28)?,
        heal_per_eat: args.flag_int("heal-per-eat", 14)?,
        eat_penalties: eat_penalties(args)?,
        preview_size: non_negative("preview-size", 50)?,
        strength_potions: args.flag_int("strength-potions", 1)?,
        max_ko_options: non_negative("max-ko-options", 0)?,
        max_builds: non_negative("max-builds", 0)?,
        magic: args.flag_int("magic", 1)? != 0,
    })
}

/// Worker threads: `--threads=N`, else every core but two so the desktop stays responsive.
fn thread_count(args: &Args) -> Result<usize> {
    let cores = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1);
    let default = cores.saturating_sub(2).max(1) as i64;
    let requested = args.flag_int("threads", default)?;
    usize::try_from(requested)
        .ok()
        .filter(|n| *n >= 1)
        .ok_or_else(|| anyhow!("--threads must be a positive integer"))
}

pub fn run(args: &Args) -> Result<()> {
    let threads = thread_count(args)?;
    rayon::ThreadPoolBuilder::new()
        .num_threads(threads)
        .build_global()
        .map_err(|e| anyhow!("cannot configure {threads} worker threads: {e}"))?;
    eprintln!("[expand-ko-kits] using {threads} worker threads");
    let ruleset = args.path(1, "ruleset")?;
    let input = args.positional(2, "input")?;
    let screen_report = args.flag("screen-report").ok_or_else(|| anyhow!("--screen-report is required"))?;
    let kits_output = args.flag("kits-output").ok_or_else(|| anyhow!("--kits-output is required"))?;
    let report_output = args.flag("report-output").ok_or_else(|| anyhow!("--report-output is required"))?;
    let config = config(args)?;
    let mechanics = MechanicRegistry::load(&ruleset.join("mechanics.json"))?;
    let items = load_items(&ruleset.join("items.json"))?;
    let kernel = CombatKernel::new(&mechanics)?;
    let report = rank_kits(
        std::path::Path::new(input),
        &python_path_string(input),
        std::path::Path::new(screen_report),
        &python_path_string(screen_report),
        &kernel,
        &items,
        &config,
    )?;
    write_kits_csv(&report, std::path::Path::new(kits_output))?;
    write_kits_report(&report, std::path::Path::new(report_output))?;
    let mut summary = match counts_document(&report) {
        Value::Object(map) => map,
        _ => unreachable!("counts document is an object"),
    };
    summary.insert("input".into(), json!(python_path_string(input)));
    summary.insert("screen_report".into(), json!(python_path_string(screen_report)));
    summary.insert("kits_output".into(), json!(python_path_string(kits_output)));
    summary.insert("report_output".into(), json!(python_path_string(report_output)));
    println!("{}", crate::canonical::pretty_sorted_json(&Value::Object(summary)));
    Ok(())
}
