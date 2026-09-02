# Status

As of 2026-09-02 the five-stage Rust pipeline is complete and verified for combat levels 30 and 40: Stages 1–4 reproduce the Python reference byte-for-byte, Stage 5 (KO-switch kits) ranks kits with a Strength potion, an amulet switch and a runes variant, a second kill-pressure ranking is reported beside the attrition ranking, Defence has been opened as a searched level with a 150-item catalog, and the PureLab viewer shows both rankings for both levels. What is not done is the thing the rankings are a proxy for: a tick-level duel solve that would replace percentile scoring with win probabilities. This page lists what is done with dates, the verified test counts, the known gaps and declared modelling limits, and the roadmap in priority order. Numbers that depend on a run are dated; see [results.md](results.md) for the rankings themselves.

## Done

| Item | Date | Evidence |
| --- | --- | --- |
| Ruleset bootstrap: 53 verified mechanics with formula ASTs and tests, 187 registered sources, source-archive hash verification, regeneration tests for items and consumables | 2026-09-01 (`data_snapshot_id: bootstrap-2026-09-01-v6`) | [`rulesets/osrs-f2p-v1`](../rulesets/osrs-f2p-v1), [`tests/`](../tests) |
| External repository audit (six projects at pinned commits; implementation references only) | 2026-09-01 | [`research/repositories/README.md`](../research/repositories/README.md) |
| Stages 1–4 ported to Rust and verified byte-identical to the Python outputs by SHA-256 on the CB30 manifest (75,665 candidates) and the top-50 full-gear manifest; report JSON identical except the echoed input path | by 2026-09-01 | [pure_math/README.md](../pure_math/README.md#byte-for-byte-verification-against-the-python-reference) (procedure); [`pure_math/tests/formula_golden.rs`](../pure_math/tests/formula_golden.rs) |
| Stage 5 `expand-ko-kits`: baseline plus out-hitting melee KO weapons, exact stack and switch-cadence KO tables, race with `inventory − switch slots` food, sixth `ko_switch` category; 918,427 kits at CB30 in 94 s on 22 threads; baseline kits equal Stage 4 for all 75,665 candidates | 2026-09-01 | [`design/2026-09-01-ko-kit-expansion-design.md`](design/2026-09-01-ko-kit-expansion-design.md), [`pure_math/tests/kits_integration.rs`](../pure_math/tests/kits_integration.rs) |
| Kill-pressure ranking (`kill_pressure`, `kill_bite`, `finish_10/15/20`, `pressure_rank`) reported alongside the attrition rank | 2026-09-01 | [`pure_math/src/kits/ko.rs`](../pure_math/src/kits/ko.rs), [`pure_math/src/kits/scores.rs`](../pure_math/src/kits/scores.rs) |
| Combat 40 pipeline (`run_pipeline.ps1`): 112,992 survivors, 1,660,515 kits; Stages 1–4 in 42 s | 2026-09-01 | [pipeline.md](pipeline.md) (per-stage sizes and runtimes) |
| Viewer: KO-kits default view, level switch 30/40, rank-by toggle (attrition vs kill pressure), glossary, KO panel tiles | 2026-09-01 | [viewer.md](viewer.md) |
| Strength potion (`--strength-potions`, default 1): potted melee hits in the KO and pressure tables, `max_burst` column; `--strength-potions=0` reproduces the previous output byte-for-byte | 2026-09-02 | [`pure_math/src/kits/ko.rs`](../pure_math/src/kits/ko.rs); [pipeline.md](pipeline.md#stage-5-expand-ko-kits) |
| Amulet switch: Amulet of strength tried with every KO weapon, kept when it raises the KO max hit; CB30 kits 918,427 → 1,168,086, CB40 1,660,515 → 2,175,645 | 2026-09-02 | [`pure_math/src/kits/enumerate.rs`](../pure_math/src/kits/enumerate.rs) |
| Magic (`--magic`, default 1): runes variant of every kit carrying the hardest out-hitting F2P spell; CB30 kits → 2,335,208, CB40 → 4,349,384; Stage 5 at CB40 about 9 min | 2026-09-02 | [`pure_math/src/kits/magic.rs`](../pure_math/src/kits/magic.rs) |
| Viewer: column picker (remembered per browser), any column sortable, copy rows as CSV (visible columns, up to 50,000 rows), glossary entries and KO-panel tiles for potion, max combo, amulet and spell | 2026-09-02 | [viewer.md](viewer.md) |
| Defence opened: catalog 84 → 150 verified items (48 with Defence requirements: bronze to rune helms, bodies, legs and shields, hardleather, studded, green d'hide body, leather cowl and gloves, four staves), requirements-parser fix, bulk `add-items` tool; `account-frontier --defence-levels`, `--keep-defensive`, `--max-ko-options`, `--max-builds`, `shortlist-survivors`, `run_stages.ps1`, `screen_chunks.ps1`; CB40 run over Defence 1/5/10/15/20/30/40 (24,084 accounts, 1,362,704 survivors, 1,152,628 kits) | 2026-09-02 | [`pure_math/src/account_frontier.rs`](../pure_math/src/account_frontier.rs), [`src/pure_solver/add_items.py`](../src/pure_solver/add_items.py) |

## Verified test counts (as of 2026-09-02)

| Suite | Count | How to run |
| --- | --- | --- |
| Rust unit tests | 63 `#[test]` functions under `pure_math/src` | `cargo test --release` in `pure_math/` |
| Rust formula golden | 1 test over a fixture of at least 600 Python-generated evaluations | same |
| Rust Stage 5 integration | 1 test on a 30-row fixture (header, counts, byte-identical reruns, CRLF, baseline kits equal Stage 4) | same |
| Python | 220 passing on 2026-09-02 (full run, about 12 minutes on a desktop) across 41 test modules | `python -m pytest tests` with `PYTHONPATH=src` (or `python -m unittest discover -s tests`) |

The whole-stage golden comparison (SHA-256 of the Rust CSV against the Python CSV) is a manual procedure (see [pure_math/README.md](../pure_math/README.md)), not an automated test; the reference outputs are large and live under the untracked `outputs/` tree.

## Current outputs (as of 2026-09-02)

| Run | Accounts | Survivors | Kits | Notes |
| --- | --- | --- | --- | --- |
| CB30, 1 Defence | 2,925 | 75,665 | 2,335,208 (potion, amulet, magic) | Kill-pressure #1: 7/52/39, 44 HP, Maple shortbow → Rune warhammer + Amulet of strength, 20.8%. |
| CB40, 1 Defence | 3,977 | 112,992 | 4,349,384 (potion, amulet, magic) | Kill-pressure #1: 21/55/51, 49 HP, same kit, 37.9%. |
| CB40, Defence 1/5/10/15/20/30/40 | 24,084 | 1,362,704 (433,845 shortlisted for Stage 5) | 1,152,628 (`--max-builds=150000 --max-ko-options=2 --magic=0`) | Pressure #1 stays 1 Defence (23.2%); attrition #1 flips to 20 Defence. |

The viewer's level-30 dataset predates the magic step (it holds the amulet-step export); level 40 is the maintained dataset. The uncapped level-40 kits file is about 0.5 GB and the export cap of 250,000 exists for that reason.

## Known gaps and modelling limits

| Gap | Effect | Where declared |
| --- | --- | --- |
| Mage pures are pruned by the account frontier: Attack, Strength, Ranged, Prayer and Hitpoints are compared and Magic is treated as filler, so a 1/1/1, 10 HP, 76 Magic account (combat 40 with Fire Blast 16 max, which beats a 14 heal) never reaches gear | Every result table lacks magic-dominant builds | [`account_frontier.rs`](../pure_math/src/account_frontier.rs) (`ranking_frontier_scope`) |
| The attrition ranking scores a patient slap fight: four of six categories are attrition and the race assumes perfect eating; kill pressure is a diagnostic without an opponent policy | The two rankings disagree by orders of magnitude on the same kits | [methodology.md](methodology.md#why-the-two-rankings-disagree) |
| Not modelled anywhere: movement and distance, projectile flight ticks, PID order, prayer in kits (offensive prayers are a fixed multiplier), shield defence loss on a 2H switch, magic-to-melee stacks, opponent switching or casting (the panel stays single-weapon with full food) | Stage 4 and 5 numbers are priority orders, not fight outcomes | Report `verification.not_modelled` |
| Opponent magic defence uses the standard 70/30 rule, which is not a verified ruleset mechanic | Magic race and pressure numbers rest on one unverified formula | Report `formula["magic.defence_roll_unverified"]` |
| Shield is not a real slot: the offensive path hardcodes Mooleta, `--keep-defensive` adds only the single most defensive legal shield, and the wooden shield is absent; no cape, boots or ring slots at all | Loadouts under-represent shield and accessory choices | [`gear_matrix.rs`](../pure_math/src/gear_matrix.rs), [`items.json`](../rulesets/osrs-f2p-v1/items.json) |
| Spells are costed bare-handed: the runes variant always charges one slot per rune type and takes no staff magic bonus, even though four elemental staves are now in the catalog as bash weapons | Bolt spells cost three slots where a staff would make it two | [`kits/magic.rs`](../pure_math/src/kits/magic.rs) |
| Every Defence level 1..40 is too big for Stage 5 (133,467 accounts, 1.36 M survivors, out of memory); the Defence run uses breakpoints and a shortlist | Defence results are for 1/5/10/15/20/30/40 only, and the kit population is the shortlist union, not every survivor | [pipeline.md](pipeline.md#stage-5-expand-ko-kits) |
| `screen_chunks.ps1` takes the representative defence rolls from chunk 01 only | Cadence columns and the Stage 5 defence states differ slightly from a single-pass Stage 3 | [pipeline.md](pipeline.md#sharding-and-merging) |
| Verified timing tables cover melee at 1–2 tiles, rapid shortbow at 2 tiles and magic at 7–8 tiles; PID reassignment and other distances fail closed | Blocks a distance-aware duel solve until experiments are run | [`research/experiments`](../research/experiments) |
| The Python CLI still runs its own math for Stages 1–4 rather than delegating to the Rust binary | Two implementations to keep in sync; Python is much slower | [`cli/`](../src/pure_solver/cli) |
| `account-frontier.json` has not been re-verified byte-for-byte since the CRLF fix to the JSON writer | The CSVs are verified; the small report file is not | [pure_math/README.md](../pure_math/README.md#byte-for-byte-verification-against-the-python-reference) |

## Roadmap

In priority order. The first item is in progress; the [README](../README.md#todo) carries the same list in player terms.

1. **Tick-level duel solve (optimal play policy).** The fight model assumes both players eat perfectly on time and never decide anything else. Replace the closed-form race with a Markov game over (my HP, their HP, both eat timers, both attack cooldowns, weapon held, food counts) solved optimally for both sides, giving a win probability per matchup; the value of a switch is then the change in win probability rather than a percentile. Run it for the 32-opponent panel times the top few thousand kits, not all kits. First version at distance 1 with no PID, because those timings are not verified.
2. **Check the winners on a real server.** Take the top kits from both rankings, play them out on a private OSRS server, and train a reinforcement-learning agent on each side of the fight ([osrs-pvp-reinforcement-learning](https://github.com/Naton1/osrs-pvp-reinforcement-learning) is the starting point). Measured win rates against the ranking will show which parts of the model hold up.
3. **Movement and distance in the fight simulation.** Every fight is at distance 1 with no projectile flight time and no PID order. Verified timings exist for melee at 1 to 2 tiles, rapid shortbow at 2 tiles and magic at 7 to 8 tiles ([`research/experiments`](../research/experiments)); anything else fails closed until the timing experiments are run.
4. **More food and inventory combinations.** Every kit carries swordfish, and the inventory options are the handful of popular setups (KO weapon, amulet swap, Strength potion, runes) used as a heuristic to keep the search tractable. Mixed food, anchovy pizza, several potions, more than one switch and prayer potions are all unexplored.
5. **Mage pures in the frontier.** Keep magic-dominant accounts as their own frontier group in Stage 1 (Magic compared, not filled), then rerun CB40 with `--magic=1` so Fire Blast accounts enter the kit population.
6. **Prayer in fights.** Offensive prayers are a fixed multiplier and protection prayers are not modelled at all, although the verified drain and protection mechanics already exist in the ruleset.
7. **Catalog gaps.** Make the shield a real slot; add the wooden shield and any missing sq shields and kiteshields to the offensive path; add cape, boots and ring slots. This is Python data work (wiki scrape plus source pinning through `add-items`), not math.
8. **Python CLI delegation.** Make `pure_solver` call the `pure_math` binary for the math stages while Python keeps `verify_source_archive` and catalog verification; keep the Python tests green.
9. **Re-verify `account-frontier.json`** byte-for-byte after the CRLF fix.
10. **Rerun and republish.** Rerun the full pipeline on the current ruleset, regenerate the viewer datasets, publish them as a new dataset release (see [`viewer/scripts/fetch_data.py`](../viewer/scripts/fetch_data.py)), and present the new top 30 alongside the Stage 3 full-gear top 30 from `resolved-ranked-top50-full.csv`.
