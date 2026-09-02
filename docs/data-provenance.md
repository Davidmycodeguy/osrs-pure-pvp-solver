# Data provenance

Every game fact the solver uses is traceable to a specific OSRS Wiki revision, and nothing reaches the ranking path without passing through a recorded human decision and a regeneration test. This page describes the verification model (truth states, source records, decisions, regeneration tests), the files that make up the ruleset, the commands for adding an item or a consumable, the catalog-audit lane that triages the 1,091 parsed wiki observations, the timing-experiment protocols for mechanics the wiki does not document precisely enough, and the licence under which wiki content is used. The Python package [`src/pure_solver`](../src/pure_solver) owns all of this; the Rust pipeline only reads the resulting `mechanics.json` and `items.json`.

## Verification model

```text
raw revision → parsed observation → evidence decision → verified snapshot → enabled mechanic
```

| Rung | Artifact | Rule |
| --- | --- | --- |
| Raw revision | [`research/authoritative/*.json`](../research/authoritative) | A wiki page at a pinned `oldid`, with retrieval time, the page's own last-edit timestamp, the SHA-256 of the wikitext, and the wikitext itself. Nothing is hand-edited. |
| Parsed observation | [`research/observations/f2p-equipment.json`](../research/observations/f2p-equipment.json) or `observe-wiki-item` output | The `Infobox Bonuses` / `Infobox Item` template fields the parser could read, plus `verification_gaps` naming what it could not (`obtainability`, `skill_requirements`, `quest_requirements`, `ammo_compatibility`, `special_mechanics`, `verified_attack_styles`). Observations are never legal equipment or consumables. |
| Evidence decision | [`item-verification.json`](../rulesets/osrs-f2p-v1/item-verification.json), [`consumable-verification.json`](../rulesets/osrs-f2p-v1/consumable-verification.json) | For every gap, `evidence_by_gap` cites one or more registered source ids; the decision also supplies fields the template does not structurally expose (attack styles, ammo ids, spell ids, two-handedness, weapon type, mechanic flags, quest requirements, availability scope). Promotion refuses a decision whose skill requirements disagree with the parsed page, whose cited sources are not registered, or whose observation is scoped to LMS/Deadman. |
| Verified snapshot | [`items.json`](../rulesets/osrs-f2p-v1/items.json), [`consumables.json`](../rulesets/osrs-f2p-v1/consumables.json), [`mechanics.json`](../rulesets/osrs-f2p-v1/mechanics.json) | Regenerated from sources plus decisions by `rebuild-items` and `rebuild-consumables`; every record carries `status: "verified"`, `availability_scope: "f2p_standard_world"` and its `source_ids`. Each snapshot has a canonical SHA-256 (`inspect` prints them). |
| Enabled mechanic | `required_mechanics` in [`manifest.json`](../rulesets/osrs-f2p-v1/manifest.json) | `MechanicRegistry.require` accepts a mechanic only if it is `verified`, has a formula version, has sources that exist in the registry, and has no unresolved `conflicts`. |

Fail-closed behaviour is enforced by the exceptions in [`errors.py`](../src/pure_solver/errors.py): `DataUnavailableError` (missing record, field, archive file or checksum mismatch), `VerifiedMechanicMissingError` (mechanic absent or not verified), `MechanicConflictError` (duplicate ids, recorded conflicts, disagreeing experiment samples). Duplicate item ids, unsourced records, members-only or unobtainable gear, unknown sources and non-terminating food transitions are all rejected at load time by `Ruleset.verify_catalogs`.

### Regeneration tests

The committed snapshots are proven regenerable on every test run rather than trusted:

| Test | What it proves |
| --- | --- |
| `tests/test_item_verification.py::test_committed_item_snapshot_regenerates_from_sources` | `items.json` equals `rebuild-items` applied to the archived pages and `item-verification.json`. |
| `tests/test_consumable_verification.py::test_committed_snapshot_regenerates_and_applies_real_transitions` and `test_strength_potion_dose_states_regenerate_from_source` | `consumables.json` food transitions and the four Strength-potion dose states regenerate from their sources. |
| `tests/test_ruleset_and_formulas.py::test_pinned_source_archive_matches_ruleset_hashes` | Every source registered in `mechanics.json` with a content hash has an archived record whose wikitext re-hashes to that value (`Ruleset.verify_source_archive`). |
| `tests/test_wiki_items.py::test_full_f2p_equipment_observation_snapshot_is_explicit` | The observation archive records its query, snapshot id, every observation and every explicit parse failure. |
| Formula tests named in each mechanic's `test_ids` (for example `test_combat_level_uses_outer_floor`, `test_accuracy_uses_strict_greater_than_branch`, `test_shortbow_rapid_is_three_ticks`) | Each formula AST evaluates as the pinned page states, floor by floor. |

Production preflight (`Ruleset.preflight`) runs the source-archive check before the required-mechanics check, so a run cannot start on an archive that no longer matches its registered hashes.

## Source records

A source record is one JSON file per page in `research/authoritative/`, written by [`sources.py`](../src/pure_solver/sources.py) from the MediaWiki API (`action=query&prop=revisions&rvprop=ids|timestamp|content`) with a descriptive User-Agent.

| Field | Meaning |
| --- | --- |
| `source_id` | `osrs-wiki:<pageid>:<revid>` for pages fetched by the fetcher; a small number of hand-named ids such as `osrs-wiki-combat-level` were registered for the bootstrap mechanics. |
| `title` | Page title as returned by the API. |
| `url` | Canonical `https://oldschool.runescape.wiki/w/<Title>?oldid=<revid>` link. |
| `revision` | The pinned revision id (`oldid`). |
| `retrieved_at` | UTC time the record was fetched. |
| `source_timestamp` | The revision's own timestamp on the wiki. |
| `content_sha256` | SHA-256 of the raw wikitext. |
| `content` | The raw wikitext. |

As of 2026-09-02 the archive holds 195 files (item pages, food and potion pages, and mechanics pages such as *Combat level*, *Attack speed*, *Successful hit*, *Free-to-play PvP techniques*, *Food/Fast foods*, *Standard spellbook*, *Prayer*, *Experience*, *Temporary skill boost*), and `mechanics.json` registers 187 source ids with their url, revision, retrieval time and content hash. Two derived files (`f2p-prayer-offence.json`, `f2p-prayer-protection.json`) are fact extracts that point back to the archived *Prayer* record rather than raw snapshots.

## Ruleset files

| File | Contents | Regenerated by |
| --- | --- | --- |
| `manifest.json` | Ruleset id, solver version, data snapshot id, retrieval timestamp, relative path of the source archive, environment (game, mode, Defence level, combat-level bounds, inventory slots), the 21 `required_mechanics`. | Hand-maintained |
| `mechanics.json` | 53 versioned mechanic records (`mechanic_id`, `status`, `value` as a formula AST or table, `formula_version`, `source_ids`, `test_ids`) and the registry of 187 sources. | `add-items` appends sources; mechanics are hand-entered with their tests |
| `items.json` | 150 verified equipment records. | `rebuild-items`, `add-items` |
| `item-verification.json` | One decision per item. | Hand-written or generated by `add-items` |
| `consumables.json` | 7 foods and the Strength potion as state-transition graphs. | `rebuild-consumables` |
| `consumable-verification.json` | Decisions for foods (expected name and item ids, transitions, evidence per gap) and potions (dose item ids, sources). | Hand-written |
| `food-scope.json` | Which foods the search optimises over (swordfish, anchovy pizza), which verified foods are dominance-pruned and by what, which observed foods are blocked and why, and exclusions. `catalog_complete: false`. | Hand-written |

Field-level detail for each file is in [`rulesets/README.md`](../rulesets/README.md).

## Adding an item

All commands run with `PYTHONPATH=src`. The one-pass tool is [`add-items`](../src/pure_solver/add_items.py): for each page title it fetches and archives the current revision (or reuses an archived one), registers the `osrs-wiki:<pageid>:<revid>` source in `mechanics.json`, parses the page, writes a decision that cites that source for every parser gap, rebuilds `items.json`, and re-verifies the source archive. Requirements are never hand-written: a page whose lead the parser cannot read is reported and skipped, and the two quest-gated items it knows about (Rune platebody, Green d'hide body) must mention Dragon Slayer I on the page.

```powershell
$env:PYTHONPATH = 'src'
python -m pure_solver add-items rulesets/osrs-f2p-v1 'Iron kiteshield' 'Wooden shield'
python -m pure_solver add-items rulesets/osrs-f2p-v1 --no-fetch      # only pages already in the archive
```

With no titles the default list is the F2P Defence armour (bronze to rune helms, bodies, legs, shields; hardleather, studded, green d'hide body, leather cowl and gloves) and the four elemental staves. Staves are registered with crush bash styles and `weapon_type: "staff"`; their spell side is modelled from the spell table, not from item data.

The manual route, useful when a decision needs fields `add-items` does not infer (ammo ids, spell ids, two-handedness, mechanic flags):

1. Preserve the page: `python -m pure_solver fetch-wiki-page 'Free-to-play PvP techniques' research/authoritative/f2p-pvp-techniques.json`.
2. Inspect what the parser sees: `python -m pure_solver observe-wiki-item 'Rune warhammer' research/observations/rune-warhammer.json`, and read its `verification_gaps`.
3. Register the source in the `sources` array of `mechanics.json` (`source_id`, `url`, `revision`, `retrieved_at`, `content_sha256`).
4. Add a decision to `item-verification.json` with `item_id`, `source_file`, `obtainable`, `availability_scope: "f2p_standard_world"`, `requirements` (must equal the parsed page), `quest_requirements`, `two_handed`, `weapon_type`, `attack_styles`, `ammo_ids`, `spell_ids`, `mechanic_flags`, and `evidence_by_gap` citing a registered source for every gap. A `notes` field records corrections (for example the Monk's robe top page, whose "Prayer level of 31" is a Monastery entry requirement, not an equip requirement).
5. Regenerate and check:

```powershell
$env:PYTHONPATH = 'src'
python -m pure_solver rebuild-items rulesets/osrs-f2p-v1 rulesets/osrs-f2p-v1/item-verification.json
python -m pure_solver inspect rulesets/osrs-f2p-v1
python -m pytest tests
```

`inspect` validates the catalogs, the source archive and the required mechanics, and prints the reproducibility metadata (ids, source revisions, item, consumable and mechanics database hashes). Then confirm the item behaves as intended for a representative account:

```powershell
python -m pure_solver gear-audit rulesets/osrs-f2p-v1 --attack 40 --strength 40 --ranged 30 --magic 1 --prayer 1 --hitpoints 40
```

which lists the legal items, every dominance removal with its dominator, and the primary/KO/ammo kits that result.

## Adding a consumable

1. Fetch the item page (and, for timing, the *Food/Fast foods* page is already archived as `osrs-wiki-fast-foods`).
2. Add a decision to `consumable-verification.json`: `consumable_id`, `expected_name`, `expected_item_ids`, `source_file`, `availability_scope`, `transitions` (per state: `healing`, `eat_delay_ticks`, `attack_delay_ticks`, `next_state`; a pizza has `full` → `half` → end) and `evidence_by_gap` for `eat_delay_ticks`, `attack_delay_ticks`, `state_transition_order`, `obtainability` and `availability_scope`. Potions list `expected_item_id_by_doses` and their sources instead.
3. Register a `food.<id>` mechanic in `mechanics.json` if the food must be a required mechanic, and decide its place in `food-scope.json` (optimised, dominance-pruned with a stated dominator, blocked with a reason, or excluded).
4. Regenerate:

```powershell
$env:PYTHONPATH = 'src'
python -m pure_solver rebuild-consumables rulesets/osrs-f2p-v1 rulesets/osrs-f2p-v1/consumable-verification.json
```

Foods with side effects that need fight state (jug of wine's Attack penalty and empty jug, kebab's random outcomes) stay `observed_but_blocked` until the state machine can represent them; members-only food (shark) is excluded with the source line that says so.

## Catalog audit lane

[`catalog.py`](../src/pure_solver/catalog.py) turns the observation archive into an auditable backlog without promoting anything. It reads `research/observations/f2p-equipment.json` (1,091 observations and 25 explicit parse failures from the query `incategory:"Free-to-play items" insource:"Infobox Bonuses"`) and, optionally, the verified `items.json`, and exposes four read-only surfaces:

| Surface | Purpose |
| --- | --- |
| `EquipmentCatalog.summary()` | Observation scale, verified coverage, pending representative groups, lineage conflicts, per-slot completeness. |
| `validation_queue()` | Deterministic parser and lineage issues to resolve before trusting promotion work. |
| `promotion_queue(account=None)` | Exact observed-equivalent items collapsed into one representative entry each (131 groups in the current snapshot), with member ids and source titles attached for audit. |
| `relevant_subset(account)` | The queue filtered to observations that look legal for a specific account, plus the verified items legal for the same account. |

Boundaries: observations stay observations; queue collapse uses only exact observed signatures, so variants that disagree on requirements or stats remain separate and also show up as a lineage conflict; `covered_by_verified_signature` is heuristic and does not authorise reusing a decision; account relevance is labelled `account_legal_by_observation` because missing or inherited requirements in source pages can still exist; LMS and Deadman variants are flagged `lms_or_deadman` and remain audit-only. The CLI front end is `catalog-audit`:

```powershell
$env:PYTHONPATH = 'src'
python -m pure_solver catalog-audit rulesets/osrs-f2p-v1 research/observations/f2p-equipment.json
```

`export-gear-catalog` writes the same triage as CSV/JSON caches for a given account (see [pipeline.md](pipeline.md#python-only-commands)). Missing requirements in an observation are never proof that an item has no requirements.

## Timing experiments

Some mechanics the wiki describes only qualitatively (projectile flight per distance, the order of phases within a tick, who wins a same-tick lethal exchange). The ruleset currently verifies a player-priority tick pipeline, immediate melee impacts at 1–2 tiles, a rapid-shortbow impact at 2 tiles, and magic impacts at 7–8 tiles, all pinned to the *Free-to-play PvP techniques*, *Attack speed* and *Standard spellbook* pages. Extending those tables requires captured evidence, not inference:

- [`research/experiments/range-to-melee-protocol.md`](../research/experiments/range-to-melee-protocol.md): the range-to-melee stack experiment (maple shortbow on rapid, then rune 2h sword, stationary target, separate sample sets per distance, RuneLite event logs plus video, at least 20 agreeing repetitions per distance).
- [`research/experiments/timing-suite-protocol.md`](../research/experiments/timing-suite-protocol.md): the five production gates (tick phase order, priority-dependent simultaneous KO, melee, ranged and magic impact timing) and the JSON shape `validate-timing-experiment` accepts (`experiment_id`, `game_version`, `evidence_manifest`, `tick_pipeline_samples`, `same_tick_ko_samples`, `impact_samples`).

```powershell
$env:PYTHONPATH = 'src'
python -m pure_solver validate-timing-experiment timing-suite.json --minimum-samples 20
```

Any disagreement between samples raises `MechanicConflictError` and is investigated rather than averaged; too few repetitions raise `DataUnavailableError`. Successful validation yields mechanic documents with `status: "experimental"`; a separate dated review must change the status to `verified` before the production ruleset accepts them.

## Attribution and licence

The wikitext in `research/authoritative/`, the observations parsed from it, and the mechanic formulas, item statistics and consumable data derived from it come from the [Old School RuneScape Wiki](https://oldschool.runescape.wiki/) and are the work of its contributors, licensed under [CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/). Each source record carries the canonical `oldid` URL of the revision it was taken from so the original page and its history can be consulted. The repository's own code licence (AGPL-3.0, see [`LICENSE`](../LICENSE)) applies to the code, not to that content; anything derived from the wiki data inherits the wiki's licence terms. Old School RuneScape is the property of Jagex; this project is an independent research tool.
