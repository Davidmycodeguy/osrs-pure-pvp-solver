# Research archive

This directory holds the raw material the solver's ruleset is built from and the protocols for extending it: pinned snapshots of OSRS Wiki pages, the parsed equipment observations that feed the catalog audit, the timing-experiment protocols for mechanics the wiki does not state precisely enough, and a commit-pinned audit of external open-source projects that were consulted as implementation references only. Nothing here is solver input on its own; every fact travels from a snapshot through a recorded decision into [`rulesets/osrs-f2p-v1`](../rulesets/osrs-f2p-v1) before the math can read it (see [`docs/data-provenance.md`](../docs/data-provenance.md)). Content taken from the wiki is licensed CC BY-NC-SA 3.0; see the notice at the end.

## Layout

| Directory | Contents | Produced by |
| --- | --- | --- |
| [`authoritative/`](authoritative) | 195 JSON files as of 2026-09-02: one pinned wiki revision per file (item pages, food and potion pages, mechanics pages such as *Combat level*, *Attack speed*, *Successful hit*, *Free-to-play PvP techniques*, *Food/Fast foods*, *Standard spellbook*, *Prayer*, *Experience*), plus two fact extracts for F2P prayers that point back to the archived *Prayer* record. | `fetch-wiki-page`, `add-items` |
| [`observations/`](observations) | `f2p-equipment.json`: 1,091 parsed equipment observations and 25 explicit parse failures from one wiki search. | `observe-wiki-search` |
| [`experiments/`](experiments) | Protocols for capturing timing evidence and the JSON contract for `validate-timing-experiment`. | Hand-written |
| [`repositories/`](repositories) | Audit of six external repositories at pinned commits, with what was adopted and what was rejected. | Hand-written, reviewed 2026-09-01 |

## Authoritative snapshots

Each file in `authoritative/` is a single wiki revision preserved verbatim so a ruleset can be independently re-audited.

| Field | Meaning |
| --- | --- |
| `source_id` | `osrs-wiki:<pageid>:<revid>`. A few bootstrap mechanics use hand-named ids such as `osrs-wiki-combat-level`; the registry in `mechanics.json` maps every id to the same url/revision/hash triple. |
| `title` | Page title as returned by the API. |
| `url` | `https://oldschool.runescape.wiki/w/<Title>?oldid=<revid>`, the permanent link to that revision. |
| `revision` | The revision id (`oldid`). |
| `retrieved_at` | UTC time the record was fetched. |
| `source_timestamp` | The revision's own timestamp on the wiki. |
| `content_sha256` | SHA-256 of the raw wikitext. |
| `content` | The raw wikitext. |

Example (abridged) from `adamant-warhammer.json`:

```json
{
  "source_id": "osrs-wiki:10259:15320176",
  "title": "Adamant warhammer",
  "url": "https://oldschool.runescape.wiki/w/Adamant_warhammer?oldid=15320176",
  "revision": "15320176",
  "retrieved_at": "2026-09-01T13:35:44.605007Z",
  "source_timestamp": "2026-08-25T22:40:35Z",
  "content_sha256": "de07bfa3…",
  "content": "{{Infobox Item ..."
}
```

### How snapshots are fetched and pinned

[`src/pure_solver/sources.py`](../src/pure_solver/sources.py) calls the MediaWiki API (`action=query`, `prop=revisions`, `rvprop=ids|timestamp|content`, `rvslots=main`) with a descriptive User-Agent and writes the record with `json.dumps(indent=2, sort_keys=True)`. The record is pinned in three places: the file itself, the `sources` array of [`rulesets/osrs-f2p-v1/mechanics.json`](../rulesets/osrs-f2p-v1/mechanics.json) (`source_id`, `url`, `revision`, `retrieved_at`, `content_sha256`), and the `source_ids` of every mechanic, item and consumable that relies on it. `Ruleset.verify_source_archive` re-hashes every archived `content` against the registered `content_sha256` on every load and test run, so an edited or missing snapshot fails closed.

```powershell
$env:PYTHONPATH = 'src'
python -m pure_solver fetch-wiki-page 'Free-to-play PvP techniques' research/authoritative/f2p-pvp-techniques.json
```

File names are lower-case slugs of the title (`archive_slug` in [`add_items.py`](../src/pure_solver/add_items.py)). Re-fetching a page that changed on the wiki produces a new revision id and hash; the old record stays valid for the ruleset that cites it until a decision is updated to cite the new one.

## Observation archive

`observations/f2p-equipment.json` is the output of `observe-wiki-search` for the query `incategory:"Free-to-play items" insource:"Infobox Bonuses"`. Its top level records `query`, `observation_snapshot_id` (a canonical hash), `observation_count`, `observations`, `failure_count` and `failures` (title, revision, error). Each observation pairs a `source` record (the same schema as above, without the wikitext) with an `observation`: item id, name, slot, requirements, bonuses, attack speed and range, combat style, `free_to_play`, `members`, `equipable`, `status: "observed"`, and `verification_gaps` naming what the template does not prove (`obtainability`, `skill_requirements`, `quest_requirements`, `ammo_compatibility`, `special_mechanics`, `verified_attack_styles`). Observations whose item name or page title mentions Last Man Standing or Deadman are tagged `environment_scope: "lms_or_deadman"` and can never be promoted.

Observations are a triage queue, not data: the catalog-audit lane ([`docs/data-provenance.md`](../docs/data-provenance.md#catalog-audit-lane)) collapses exact duplicates into representative groups and reports lineage conflicts, and a human writes a decision citing evidence for every gap before an item enters `items.json`.

## Experiments

| Protocol | Covers |
| --- | --- |
| [`experiments/range-to-melee-protocol.md`](experiments/range-to-melee-protocol.md) | The range-to-melee stack: maple shortbow on rapid with adamant arrows, then rune 2h sword, against a stationary 1×1 target, separate sample sets per distance, RuneLite `GameTick`/projectile/animation/equipment/hitsplat events plus video, at least 20 agreeing repetitions per distance. |
| [`experiments/timing-suite-protocol.md`](experiments/timing-suite-protocol.md) | The five production gates the wiki does not fully document: tick phase order, priority-dependent simultaneous KO, melee impact timing, ranged projectile timing, magic projectile timing; and the JSON input of `python -m pure_solver validate-timing-experiment`. |

Wall-clock duration is never a substitute for logical ticks. Disagreeing samples raise `MechanicConflictError` and are investigated rather than averaged; validated results are labelled `experimental` and need a dated review decision before the production ruleset accepts them.

## Repositories audit

[`repositories/README.md`](repositories/README.md) records six projects reviewed at pinned commits on 2026-09-01: weirdgloop/osrs-dps-calc, Palfore/OSRSmath, runelite/runelite, JarateKing/histogram, ArtemisRS/savant and Y-o-r-o/OSRSCombatSim. For each it lists the files reviewed, the useful findings and the adoption decision. The pattern adopted from them is methodological (formula ASTs with golden tests, exact-first evaluators with explicit search budgets, separation of logical ticks from client-observed timing, seeded simulation with declared unsupported mechanics, canonical inventory state). None is a game-mechanics authority: no value, timing constant or formula was copied from them, calculator code is never a tiebreaker against a source record, and mechanics enter the solver only after a separately cited source record and an explicit verification test.

## Attribution and licence

The wikitext stored in `authoritative/`, the observations in `observations/`, and all data derived from them (the item statistics, consumable timings, spell table and formula constants in [`rulesets/osrs-f2p-v1`](../rulesets/osrs-f2p-v1)) are © the contributors of the [Old School RuneScape Wiki](https://oldschool.runescape.wiki/) and are used under the [Creative Commons Attribution-NonCommercial-ShareAlike 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/) licence. Every record carries the permanent `oldid` URL of the revision it reproduces. The repository's code licence (AGPL-3.0, [`LICENSE`](../LICENSE)) does not apply to this content; redistribution of the snapshots or of data derived from them must follow the wiki's licence terms. Old School RuneScape is the property of Jagex Ltd; this archive is maintained for independent, non-commercial research.
