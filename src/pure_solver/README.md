# `pure_solver`: the Python data, verification and reference lane

`pure_solver` is the Python half of the OSRS F2P pure PvP build solver. It pins OSRS Wiki
revisions, turns review decisions into the verified ruleset under `rulesets/osrs-f2p-v1`, audits
the equipment catalog, and holds the original implementation of pipeline Stages 1 to 4, which the
Rust crate [`pure_math`](../../pure_math/README.md) reproduces byte for byte. It also carries the
exploratory duel solvers that are not on the ranking path. The package has **no runtime
dependencies** and needs Python 3.11 or newer.

## Running the CLI

From a checkout, without installing anything:

```sh
PYTHONPATH=src python -m pure_solver --help
PYTHONPATH=src python -m pure_solver inspect rulesets/osrs-f2p-v1
```

PowerShell:

```powershell
$env:PYTHONPATH='src'; python -m pure_solver --help
```

Or install the package (editable, with the dev tools) and use the `pure-solver` script:

```sh
python -m pip install -e ".[dev]"
pure-solver --help
pure-solver inspect rulesets/osrs-f2p-v1
pure-solver gear-audit rulesets/osrs-f2p-v1 --attack 40 --strength 40 --ranged 30 --magic 1 --prayer 1 --hitpoints 40
```

Every subcommand takes the ruleset directory first and prints a small JSON summary. A
`SolverError` (missing, unverified or conflicting data) prints `ErrorType: message` on stderr and
exits with status 2; `solve` and `solve-active` instead emit a JSON payload with
`verification.status = "blocked"` and exit 2. The subcommands, grouped as in `cli/`:

| Module | Subcommands |
| --- | --- |
| `cli/data.py` | `inspect`, `fetch-wiki-page`, `observe-wiki-item`, `observe-wiki-search`, `add-items`, `rebuild-items`, `rebuild-consumables` |
| `cli/audit.py` | `gear-audit`, `catalog-audit`, `export-gear-catalog`, `validate-timing-experiment` |
| `cli/matrix.py` | `export-gear-matrix`, `export-exact-gear-matrix`, `screen-gear-matrix` |
| `cli/pipeline.py` | `account-frontier` (Stage 1), `export-account-gear-matrix` (Stage 2), `screen-resolved-gear-matrix` (Stage 3), `rank-resolved-survivors` (Stage 4), `select-top-accounts` |
| `cli/offense.py` | `offense-frontier`, `merge-frontiers` (exploratory) |
| `cli/solve.py` | `solve`, `solve-active` (exploratory) |

[`docs/pipeline.md`](../../docs/pipeline.md) lists every flag and default.

## Running the tests

```sh
python -m pip install -e ".[dev]"      # or: python -m pip install pytest ruff
python -m pytest tests -q              # tests/conftest.py adds src/ to sys.path
python -m ruff check src tests
python -m ruff format --check src tests
```

The suite takes several minutes because a few tests run the offense frontier and the duel solver end
to end; `python -m pytest tests -q -x --durations=10` shows where the time goes.

## Fail-closed design

Game mechanics enter the solver only as versioned, sourced, verified records: every entry in
`mechanics.json` and `items.json` cites pinned OSRS Wiki revisions kept in the ruleset's source
archive, and `Ruleset.preflight()` / `Ruleset.verify_source_archive()` refuse to run on anything
that is unverified, out of scope, or no longer matches the archived page. When a required
mechanic or data field is missing, unverified or contradicted, the code raises
`DataUnavailableError`, `VerifiedMechanicMissingError` or `MechanicConflictError` (all subclasses
of `SolverError`) instead of guessing, and every report carries a `verification` block that says
what the numbers do and do not model.

## Module map

"Golden reference" means the Rust port is verified byte for byte against this module's output and
the Python stays the reference implementation. Rust paths are relative to `pure_math/src/`.
"Primitive" marks verified mechanic building blocks that are covered by tests but not yet wired
into the ranking pipeline.

| Module | Purpose | Rust counterpart | Golden reference |
| --- | --- | --- | --- |
| `__init__.py` | Package exports: the error types, the `PrayerBook` family, `Ruleset` and `load_ruleset`. | | |
| `__main__.py` | `python -m pure_solver` entry point. | `main.rs` | |
| `cli/__init__.py` | CLI package; re-exports `main` and `build_parser`. | `cli.rs`, `commands/` | |
| `cli/__main__.py` | Keeps `python -m pure_solver.cli` working. | | |
| `cli/parser.py` | `build_parser()` and `main()`; the subcommand registration order. | | |
| `cli/common.py` | Shared CLI helpers: level-range options, account modes, wiki-first item merging. | | |
| `cli/data.py` | Ruleset inspection, Wiki pinning and item/consumable rebuild subcommands. | | |
| `cli/audit.py` | Gear, catalog and timing-experiment audit subcommands. | | |
| `cli/matrix.py` | Band and exact gear-matrix export plus the static screen. | | |
| `cli/pipeline.py` | Stage 1 to 4 subcommands and `select-top-accounts`. | `commands/` | |
| `cli/offense.py` | Closed-form offense frontier and shard merge. | | |
| `cli/solve.py` | Bounded duel solver and active-set solver subcommands. | | |
| `errors.py` | Fail-closed exception hierarchy (`SolverError` and friends). | | |
| `canonical.py` | Canonical JSON and SHA-256 identifiers. | `canonical.rs` | yes |
| `formula.py` | Exact JSON formula AST evaluator (integers and `Fraction` only). | `formula.rs`, `tests/formula_golden.rs` | yes |
| `mechanics.py` | Verified mechanic registry with source provenance; `require`/`evaluate` fail closed. | `mechanics.rs` (mirrors `require`) | |
| `ruleset.py` | Loads a ruleset directory into an immutable `Ruleset`; preflight and archive verification. | | |
| `sources.py` | Fetches pinned OSRS Wiki revisions and persists raw source records. | | |
| `wiki_items.py` | Parses equipment pages into unpromoted `WikiItemObservation`s. | | |
| `wiki_consumables.py` | Parses food pages into `WikiConsumableObservation`s. | | |
| `wiki_potions.py` | Parses the Strength potion page into a `WikiPotionObservation`. | | |
| `item_verification.py` | Review decisions plus observations to verified (or provisional wiki-trusted) item documents. | | |
| `consumable_verification.py` | Review decisions plus observations to verified food documents. | | |
| `potion_verification.py` | Review decisions plus observation to the verified Strength potion document. | | |
| `add_items.py` | One-pass archive, register, verify and rebuild for a list of equipment page titles. | | |
| `catalog.py` | Observation catalog: duplicate groups, validation queue, promotion queue, completeness summary. | | |
| `catalog_scope.py` | Catalog-scope audit: status groups and exhaustive-claim safety. | | primitive |
| `experiments.py` | Derives timing claims from empirical experiment documents. | | |
| `accounts.py` | `AccountState`, `LevelRange`, `AccountSearchBounds` and lazy account enumeration. | `accounts.rs` | |
| `experience.py` | XP tables and the Hitpoints levels ordinary F2P training can reach. | `experience.rs` (ranking-path parts) | yes |
| `legality.py` | `EquipmentItem`, `Loadout`, `LegalityContext` and legality checks. | `items.rs` | |
| `dominance.py` | Strict per-account item dominance with audit records. | `dominance.rs` | yes |
| `prayers.py` | Best verified prayer boost sets per prayer level (pipeline). | `prayers.rs` | yes |
| `prayer_book.py` | Full prayer catalogue with drain, conflicts and flicking (simulation). | | |
| `kits.py` | Primary plus KO-switch combat kits and their inventory cost. | (`kits/` is the Rust-only Stage 5, not a port) | |
| `inventory.py` | Immutable inventory state with data-defined consume transitions. | | |
| `allocations.py` | Count-equivalent inventory allocations for a kit. | | |
| `consumable_dominance.py` | Dominance pruning over verified foods. | | |
| `usage.py` | Per-fight consumable usage and population summaries. | | |
| `profiles.py` | Melee and ranged attack profiles from pinned formulas. | | |
| `account_frontier.py` | Stage 1: exact combat-level 1-Defence accounts and their Pareto frontier. | `account_frontier.rs` | yes |
| `account_gear_matrix.py` | Stage 2: attach gear to exact accounts, cached per unlock signature. | `gear_matrix.rs` | yes |
| `gear_matrix.py` | Gear-matrix rows (band or exact account) and the JSON/CSV writers. | `gear_matrix.rs` (row builder), `matrix_table.rs`, `io.rs` | yes |
| `gear_catalog_export.py` | Account-local gear export and level-band item profiles. | | |
| `gear_screen.py` | Conservative static screen of a gear matrix with diverse seeds. | `resolved_screen.rs` (candidate construction) | |
| `candidate_reduction.py` | Exact-duplicate removal, Pareto pruning and seed selection with audits. | `reduction.rs` | yes |
| `resolved_gear_screen.py` | Stage 3: exact integer style resolution, KO cadence, Pareto prune, survivor manifest. | `resolved_screen.rs`, `combat.rs` | yes |
| `survivor_ranking.py` | Stage 4: opponent panel, food-race margins, category scores, ranked CSV and report. | `ranking/` | yes |
| `evaluation.py` | Damage PMFs, exact first-strike win probability, Monte Carlo, zero-sum solvers. | | |
| `events.py` | Generic tick engine configured from verified mechanics. | | |
| `duel.py` | Logical-tick duel simulator and policies. | | |
| `matchups.py` | Monte Carlo matchups, adaptive sampling and the matchup matrix. | | |
| `optimization.py` | Restricted policy grid and objective ranking. | | |
| `reporting.py` | `SolveReport` dataclasses and ranking/counter/Pareto builders. | | |
| `game_solver.py` | Evaluates a materialised strategy space into a `SolveReport`. | | |
| `solver.py` | Bounded melee/ranged duel solver behind `solve` (exploratory). | | |
| `combat_envelope.py` | Exact raw-burst envelopes with window and adaptive KO metrics. | | |
| `double_oracle.py` | Sparse two-sided double oracle for zero-sum games. | | |
| `active_solver.py` | Active-set duel solver behind `solve-active` (exploratory). | | |
| `frontier.py` | Closed-form offense frontier behind `offense-frontier` (exploratory). | | |
| `frontier_merge.py` | Merges offense-frontier shards with identical scope. | | |
| `latency.py` | Input timing and latency acceptance model. | | primitive |
| `magic.py` | Verified F2P spells and magic attack profiles. | | primitive |
| `movement.py` | Tile movement resolution. | | primitive |
