# pure_math

`pure_math` is the exact-arithmetic math pipeline behind the `pure` solver, a build search for
Old School RuneScape free-to-play "pure" PvP accounts. Starting from a target combat level it
enumerates every reachable account skill profile, attaches all legal F2P gear, screens each build
with exact combat formulas (arbitrary-precision rationals, never floats), ranks the survivors, and
finally expands each survivor into knock-out (KO) switch kits. Stages 1-4 are ports of the Python
reference in [`../src/pure_solver`](../src/pure_solver) and reproduce its output files byte for
byte; Stage 5 (`expand-ko-kits`) exists only in Rust. The mathematics is described in
[`../docs/pipeline.md`](../docs/pipeline.md) and [`../docs/methodology.md`](../docs/methodology.md);
the Stage 5 design is in
[`../docs/design/2026-09-01-ko-kit-expansion-design.md`](../docs/design/2026-09-01-ko-kit-expansion-design.md).

## Building

```sh
cd pure_math
cargo build --release
```

The binary is `pure_math\target\release\pure_math.exe` on Windows and
`pure_math/target/release/pure_math` on Linux/macOS. Always use `--release`: the profile enables
thin LTO and a single codegen unit, and Stage 5 is CPU-bound. Run the binary from the repository
root so the ruleset path (`rulesets/osrs-f2p-v1`) and the default `outputs/...` paths resolve.

- `pure_math` with no arguments, or `pure_math version`, prints the crate version.
- `pure_math help`, `pure_math --help` and `pure_math -h` print the usage text and exit 0.
- Every flag is written `--name=value` or `--name value`.

## Pipeline

All stages take the ruleset directory first (`rulesets/osrs-f2p-v1`, holding `items.json` and
`mechanics.json`). Flags are listed with their defaults; flags marked *required* have none.

| Stage | Subcommand | Input | Output | Key flags (default) | Typical runtime |
|---|---|---|---|---|---|
| 1 | `account-frontier <ruleset>` | ruleset only | `--ranking-output` (`outputs/cb30/accounts-ranking.csv`), `--full-output` (`outputs/cb30/accounts-full.csv`), `--report-output` (`outputs/cb30/account-frontier.json`) | `--combat-level=30`, `--defence-levels=1` (a level, a range such as `1-40`, or a list such as `1,5,10`) | part of the 42 s for Stages 1-4 (1) |
| 2 | `export-account-gear-matrix <ruleset> <accounts.csv>` | Stage 1 ranking-frontier CSV | `--csv-output` (`outputs/cb30/gear-matrix.csv`) | `--kit-mode=offence_pareto` (or `full`), `--keep-defensive=false`, `--completed-quests=<name;name>` (default: none) | part of (1) |
| 3 | `screen-resolved-gear-matrix <ruleset> <matrix.csv>` | Stage 2 gear matrix | `--manifest-output` (`outputs/cb30/resolved-survivors.csv`), `--report-output` (`outputs/cb30/resolved-screen-report.json`) | `--audit-limit=20` | part of (1) |
| 4 | `rank-resolved-survivors <ruleset> <manifest.csv>` | Stage 3 survivor manifest | `--ranked-output` (*required*), `--report-output` (*required*) | `--panel-size=32`, `--food-slots=28`, `--heal-per-eat=14`, `--eat-penalties=3,0`, `--preview-size=50` | about 7 s at combat level 30 (1) |
| 5 | `expand-ko-kits <ruleset> <manifest.csv> --screen-report=<stage-3 report>` | Stage 3 survivor manifest and screen report | `--kits-output` (*required*), `--report-output` (*required*) | `--panel-size=32`, `--inventory-slots=28`, `--heal-per-eat=14`, `--eat-penalties=3,0`, `--preview-size=50`, `--strength-potions=1`, `--max-ko-options=0` (0 = all), `--max-builds=0` (0 = all), `--magic=1` (1/0), `--threads=<cores minus two>` | about 94 s at combat level 30 (918k kits); 4-9 min at combat level 40 (2) |

(1) Stages 1-4 together take about 42 s for combat level 40 on a 22-thread desktop.
(2) Stage 5 time depends on how many potion, amulet-switch and magic variants the options produce.

`--eat-penalties` is a comma-separated list of eat penalties in ticks and must include both `3`
and `0`. `--max-builds` in Stage 5 keeps only the union of the top-N survivors by sustained DPT,
by Strength (then potted max hit) and by physical defence before expanding kits.

A full run for combat level 40 (what `scripts/run_pipeline.ps1` does, with `<out>` =
`outputs/cb40-rust`):

```sh
pure_math account-frontier rulesets/osrs-f2p-v1 --combat-level=40 --defence-levels=1 \
  --ranking-output=<out>/accounts-ranking.csv --full-output=<out>/accounts-full.csv --report-output=<out>/account-frontier.json
pure_math export-account-gear-matrix rulesets/osrs-f2p-v1 <out>/accounts-ranking.csv \
  --kit-mode=offence_pareto --keep-defensive=true "--completed-quests=Dragon Slayer I" --csv-output=<out>/gear-matrix-cb40-offence.csv
pure_math screen-resolved-gear-matrix rulesets/osrs-f2p-v1 <out>/gear-matrix-cb40-offence.csv \
  --manifest-output=<out>/resolved-survivors-cb40.csv --report-output=<out>/resolved-screen-cb40.json
pure_math rank-resolved-survivors rulesets/osrs-f2p-v1 <out>/resolved-survivors-cb40.csv \
  --ranked-output=<out>/resolved-ranked-cb40.csv --report-output=<out>/resolved-ranking-cb40.json
pure_math expand-ko-kits rulesets/osrs-f2p-v1 <out>/resolved-survivors-cb40.csv --screen-report=<out>/resolved-screen-cb40.json \
  --kits-output=<out>/kits-cb40.csv --report-output=<out>/kits-cb40.json --max-ko-options=4
```

Each stage prints a small JSON summary (counts and output paths) on stdout; Stage 5 also logs
its phases and progress on stderr.

### Extra command: `shortlist-survivors`

```
pure_math shortlist-survivors <ruleset> <manifest.csv> --output=<csv> [--max-builds=0]
```

Writes the subset of a Stage 3 manifest that Stage 5 would keep under the same `--max-builds`
rule, as a smaller manifest with identical columns, so Stage 4 and Stage 5 can be run on one
bounded population. `--max-builds=0` keeps every row.

## Scripts

The scripts in [`scripts/`](scripts) drive the release binary from the repository root (each
resolves the root from its own path and changes to it) and write to `outputs/cb<level>-rust/`.
Build first with `cargo build --release` (`run_pipeline.sh` builds it for you if it is missing).

| Script | What it does |
|---|---|
| `run_pipeline.ps1` | Stages 1-5 for one combat level: `powershell -File pure_math\scripts\run_pipeline.ps1 -CombatLevel 40`. Parameters: `-DefenceLevels '1'` (a list such as `'1,5,10,15,20,30,40'` opens Defence up; `'1-40'` at once runs out of memory at Stage 5), `-MaxKoOptions 4`, `-CompletedQuests 'Dragon Slayer I'`, `-KeepDefensive 'true'`, `-Threads 0` (0 = let Stage 5 choose). |
| `run_pipeline.sh` | Linux/macOS equivalent of `run_pipeline.ps1`: `pure_math/scripts/run_pipeline.sh [combat_level=40] [defence_levels=1] [max_ko_options=4] [threads=0]`, with `COMPLETED_QUESTS` and `KEEP_DEFENSIVE` read from the environment. |
| `run_stages.ps1` | A subset of Stages 2-5 (`-Stages 2,3,4`) when the earlier outputs already exist; adds `-MaxBuilds 0` and `-Magic 1` for Stage 5. |
| `rerun_kits.ps1` | Stage 5 only (default flags) for `-Levels 40` or `-Levels 30,40`, then `viewer\scripts\export_build_data.py <level>` to refresh the viewer data. |
| `screen_chunks.ps1` | Stage 3 over a pre-split gear matrix (`chunks\gear-<n>.csv`) to bound memory, then concatenates the chunk manifests into `resolved-survivors-cb<level>.csv` and copies `chunks\screen-01.json` to `resolved-screen-cb<level>.json`. |

## Tests

```sh
cd pure_math
cargo test --release
```

The crate must sit inside the repository checkout: both integration tests read
`../rulesets/osrs-f2p-v1/`.

- **Unit tests** (63) live next to the code in `src/` and cover the rational type, canonical
  JSON, formula evaluation, account and gear enumeration, dominance, reduction, ranking and the
  Stage 5 kit logic.
- **`tests/formula_golden.rs`** loads `tests/fixtures/formula-golden.json`, which
  `golden/generate_formula_golden.py` produced by running the Python reference
  (`pure_solver.formula.evaluate`) over deterministic sampled inputs for every formula mechanic in
  the ruleset (at least 600 cases). Every case must evaluate to exactly the same numerator and
  denominator, and cases the reference rejected must still error. Regenerate the fixture from the
  repository root with `PYTHONPATH=src python pure_math/golden/generate_formula_golden.py`
  (PowerShell: `$env:PYTHONPATH='src'; python pure_math/golden/generate_formula_golden.py`).
- **`tests/kits_integration.rs`** runs Stage 5 on the 30-row fixture
  `tests/fixtures/kits/resolved-survivors-sample.csv` with
  `tests/fixtures/kits/resolved-screen-sample.json`. It checks the CSV header equals
  `KIT_FIELDS`, that every survivor gets exactly one baseline kit, that two runs are
  byte-identical (CRLF included), that baseline kits reproduce Stage 4's race numbers and Stage 3's
  cadence KO probabilities, that a carried Strength potion costs one slot and never lowers kill
  pressure, and that magic variants appear only when the spell out-hits the primary weapon.

### Byte-for-byte verification against the Python reference

Stages 1-4 are golden-tested against the Python CLI outputs rather than against fixtures. Run the
Python stage and the Rust stage on the same inputs, then:

- **CSV files** (accounts, gear matrix, survivor manifest, ranked survivors): compare SHA-256
  hashes (`sha256sum a.csv b.csv`, or `Get-FileHash` in PowerShell). They must be identical.
- **Report JSON files**: `diff` them. The only permitted difference is the echoed `"input"` path
  line, which repeats the input argument exactly as it was given on each command line.

## Invariants

- **Exact arithmetic.** `Rational` (`src/rational.rs`) is a pair of `BigInt`s kept in lowest terms
  with a positive denominator, mirroring Python's `fractions.Fraction`. Combat and KO-window
  denominators exceed 64 bits, so `serde_json` is built with `arbitrary_precision` and big
  numerators and denominators are written verbatim.
- **Canonical hashes.** Candidate ids and signatures are
  `sha256(json.dumps(normalise(v), separators=(",",":"), sort_keys=True, ensure_ascii=True))`, with
  every `Fraction` normalised to `{"numerator": ..., "denominator": ...}`; `src/canonical.rs`
  reproduces that byte stream exactly.
- **Line endings.** CSV output always uses CRLF (Python's `csv.writer` default); JSON and text
  output follow Python text mode, so they are CRLF on Windows (where the reference outputs were
  produced) and LF elsewhere. Do not "fix" the line endings: the golden hashes depend on them.
- **Combat level.** Combat level 30 means the exact combat-level numerator lies in
  `[4800, 4959]`. The combat formula is pinned to OSRS Wiki revision
  `osrs-wiki-combat-level-15305725` in `rulesets/osrs-f2p-v1/mechanics.json`; every mechanic the
  kernel uses must be marked verified and conflict-free in that file.
- **Ranked CSV layout.** The Stage 4 CSV has 59 fixed fields (`RANKED_FIELDS` in
  `src/ranking/output.rs`) followed by every column of the source manifest, in manifest order.
- **Stage 5 convolutions.** `PmfCache` (`src/kits/ko.rs`) caches per-style damage distributions
  once per run. Convolutions run in a dense `u128` integer form with one shared denominator and
  fall back to exact big fractions on overflow; both paths yield the same normalised fractions.
- **Determinism.** Work is parallelised with `rayon`, but results are collected in input order,
  so identical inputs and flags produce identical bytes (the kits integration test asserts this).
