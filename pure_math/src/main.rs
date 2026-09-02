//! Command-line entry point.  Stages 1-4 mirror the `pure_solver` CLI stages and
//! write the same files, so the two implementations can be diffed byte for byte;
//! `expand-ko-kits` (Stage 5) and `shortlist-survivors` exist only here.

use anyhow::Result;
use pure_math::cli::Args;
use pure_math::commands;

const USAGE: &str = "\
pure_math <subcommand> [args]
  version
  help | --help | -h
  account-frontier <ruleset> [--combat-level=30] [--defence-levels=1] [--ranking-output=outputs/cb30/accounts-ranking.csv] [--full-output=outputs/cb30/accounts-full.csv] [--report-output=outputs/cb30/account-frontier.json]
  export-account-gear-matrix <ruleset> <accounts.csv> [--kit-mode=offence_pareto] [--keep-defensive=false] [--completed-quests=<quest;quest>] [--csv-output=outputs/cb30/gear-matrix.csv]
  screen-resolved-gear-matrix <ruleset> <matrix.csv> [--manifest-output=outputs/cb30/resolved-survivors.csv] [--report-output=outputs/cb30/resolved-screen-report.json] [--audit-limit=20]
  rank-resolved-survivors <ruleset> <manifest.csv> --ranked-output=.. --report-output=.. [--panel-size=32] [--food-slots=28] [--heal-per-eat=14] [--eat-penalties=3,0] [--preview-size=50]
  expand-ko-kits <ruleset> <manifest.csv> --screen-report=.. --kits-output=.. --report-output=.. [--panel-size=32] [--inventory-slots=28] [--heal-per-eat=14] [--eat-penalties=3,0] [--preview-size=50] [--strength-potions=1] [--max-ko-options=0] [--max-builds=0] [--magic=1] [--threads=<cores minus two>]
  shortlist-survivors <ruleset> <manifest.csv> --output=.. [--max-builds=0]
Flags in [..] show their default; flags without brackets are required.  Flags take --name=value or --name value.
  --defence-levels: a level, a range or a list (1, 1-40, 1,5,10).  --kit-mode: offence_pareto or full.
  --keep-defensive: true or false.  --completed-quests: ';'-separated quest names (default none).
  --eat-penalties: comma-separated eat penalties in ticks; must include 3 and 0.
  --max-ko-options, --max-builds: 0 means unlimited.  --magic: 1 or 0.  --threads: default is every core but two (at least one).";

const HELP_WORDS: [&str; 3] = ["help", "--help", "-h"];

fn main() -> Result<()> {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    if raw.first().is_some_and(|word| HELP_WORDS.contains(&word.as_str())) {
        println!("{USAGE}");
        return Ok(());
    }
    let args = Args::parse(&raw)?;
    match args.positional(0, "subcommand").unwrap_or("version") {
        "version" => {
            println!("pure_math {}", env!("CARGO_PKG_VERSION"));
            Ok(())
        }
        "account-frontier" => commands::account_frontier::run(&args),
        "export-account-gear-matrix" => commands::gear_matrix::run(&args),
        "screen-resolved-gear-matrix" => commands::screen::run(&args),
        "rank-resolved-survivors" => commands::rank::run(&args),
        "expand-ko-kits" => commands::kits::run(&args),
        "shortlist-survivors" => commands::shortlist::run(&args),
        other => anyhow::bail!("unknown subcommand {other:?}\n{USAGE}"),
    }
}
