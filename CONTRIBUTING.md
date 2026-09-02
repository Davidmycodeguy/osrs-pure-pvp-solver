# Contributing

Thanks for taking an interest. This project is small enough that a good issue or a focused pull request is the whole process. A few rules keep the numbers trustworthy.

## Ground rules

- **Mechanics need a source.** Nothing enters `rulesets/osrs-f2p-v1` from memory. A new item, spell, food, prayer or timing rule needs a pinned OSRS Wiki revision (or a documented experiment) in `research/authoritative`, a review decision in the matching `*-verification.json`, and a test. See [docs/data-provenance.md](docs/data-provenance.md).
- **Stages 1–4 are golden.** The Rust stages `account-frontier`, `export-account-gear-matrix`, `screen-resolved-gear-matrix` and `rank-resolved-survivors` must keep producing byte-identical output to the Python reference in `src/pure_solver`. If you change one side, change the other and re-run the hash comparison described in [pure_math/README.md](pure_math/README.md).
- **Exact arithmetic only on the ranking path.** Probabilities, damage-per-tick and margins are exact rationals. `f64` is for display columns.
- **Fail closed.** When a mechanic is missing, unverified or contradictory, raise the typed error. Never fall back to a guess.

## Development setup

```bash
# Python (data lane + reference implementation)
python -m pip install -e ".[dev]"
python -m pytest tests -q
python -m ruff check src tests
python -m ruff format --check src tests

# Rust (math pipeline)
cd pure_math
cargo fmt --check && cargo clippy --release --all-targets -- -D warnings && cargo test --release

# Viewer
cd viewer
npm ci
npx oxlint && npx tsc --noEmit && npm run build
```

The CI workflow in `.github/workflows/ci.yml` runs these same checks on every push and pull request.

## Pull requests

1. Open an issue first for anything that changes a mechanic, a ranking formula or an output format.
2. Keep pull requests focused. Refactors and behaviour changes go in separate PRs.
3. Add or update tests. Rust changes on the ranking path must keep `cargo test --release` (including the golden and integration tests) green.
4. Use conventional commit messages: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `perf:`.
5. If you regenerate pipeline outputs, say which command, which options and which machine, and paste the report's `verification` block into the PR.

## Reporting a wrong number

Wrong numbers are the most valuable bug reports. Please include the kit or build ID from the viewer (search for `#rank` or the candidate ID), the combat level, and what you expected with a link to the wiki page or an in-game observation.

## License

By contributing you agree that your contributions are licensed under the [GNU AGPL-3.0](LICENSE). Data derived from the OSRS Wiki stays under CC BY-NC-SA 3.0 as described in [research/README.md](research/README.md).

## What is where

```text
pure/
├── src/pure_solver/     Python data lane, verification, reference implementation, CLI
├── tests/               Python test suite (pytest)
├── pure_math/           Rust pipeline crate: src/, tests/, golden fixtures, run scripts
├── viewer/              PureLab React app and the export and fetch scripts
├── rulesets/osrs-f2p-v1 Verified mechanics, items, consumables and review decisions
├── research/            Pinned wiki snapshots, parsed observations, experiment protocols
├── docs/                Architecture, pipeline, methodology, results, status, screenshots
└── outputs/             Generated pipeline outputs (git-ignored, multi-GB)
```

| Component | Language | Role |
| --- | --- | --- |
| `src/pure_solver` | Python 3.11+, no dependencies | Fetches and pins wiki revisions, applies review decisions, rebuilds the verified ruleset, audits the catalog. Also the reference implementation of stages 1 to 4. See [docs/data-provenance.md](docs/data-provenance.md). |
| `pure_math` | Rust | The production math pipeline. Stages 1 to 4 reproduce the Python reference byte for byte; stage 5, knockout-switch kits, exists only here. See [pure_math/README.md](pure_math/README.md). |
| `viewer` | React 19, TypeScript | PureLab, the build explorer. See [docs/viewer.md](docs/viewer.md). |

What is done, the verified test counts and the known gaps live in [docs/status.md](docs/status.md).
