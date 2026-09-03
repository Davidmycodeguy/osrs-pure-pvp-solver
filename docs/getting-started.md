# Getting started

Three ways in, from easiest to most involved. Pick the one that matches what you want to do.

| I want to | Do this | Needs |
| --- | --- | --- |
| Look at the ranked builds and explore them | [Run the viewer](#run-the-viewer) | Node 22.13+, Python 3.11+ |
| Recompute the rankings myself, or try a different combat level | [Run the pipeline](#run-the-pipeline) | Rust toolchain, a few GB of disk |
| Add an item, fix a mechanic, or work on the data | [Work on the data](#work-on-the-data) | Python 3.11+ |

## Run the viewer

The viewer (PureLab) is a browser app that loads the ranked builds and knockout kits for one combat level, lets you filter and sort them, and explains every number. The datasets are downloaded from the GitHub release, so you do not need Rust or the pipeline for this.

```bash
git clone https://github.com/Davidmycodeguy/osrs-pure-pvp-solver.git
cd pure/viewer
npm ci
python scripts/fetch_data.py        # ~56 MB of gzipped datasets from the GitHub release
npm run dev                         # app on http://localhost:3000
```

[viewer.md](viewer.md) is a tour of the interface and a glossary of the columns.

## Run the pipeline

The classic 1-Defence search at combat level 40 takes about a minute for stages 1 to 4 and several minutes for stage 5 on a modern desktop. It writes a few GB under `outputs/`.

```bash
cd pure_math && cargo build --release && cd ..

# Linux / macOS
pure_math/scripts/run_pipeline.sh 40 1

# Windows
powershell -File pure_math\scripts\run_pipeline.ps1 -CombatLevel 40 -DefenceLevels '1'

# Export for the viewer
python viewer/scripts/export_build_data.py 40
```

To open Defence up, pass a list of levels such as `1,5,10,15,20,30,40` instead of `1`; that run is far larger and needs the [sharding and shortlist steps](pipeline.md#sharding-and-merging), and every level from 1 to 40 at once runs out of memory at stage 5. Every stage, flag and output file is documented in [pipeline.md](pipeline.md), and the Rust crate has its own [README](../pure_math/README.md).

## Work on the data

```bash
python -m pip install -e ".[dev]"
python -m pytest tests -q                      # 220 tests, about 12 minutes
pure-solver inspect rulesets/osrs-f2p-v1       # validate the ruleset and print its provenance
pure-solver gear-audit rulesets/osrs-f2p-v1 --attack 40 --strength 40 --ranged 30 --magic 1 --prayer 1 --hitpoints 40
```

Adding an item means pinning its wiki page, recording a review decision and regenerating the snapshot. [data-provenance.md](data-provenance.md) walks through it step by step. [CONTRIBUTING.md](../CONTRIBUTING.md) covers the repository layout and the checks that run in CI.
