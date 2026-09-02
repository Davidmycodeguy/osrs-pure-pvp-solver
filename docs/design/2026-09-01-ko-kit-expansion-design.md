# Stage 5 — KO-switch kit expansion (`expand-ko-kits`) design

Date: 2026-09-01
Status: implemented 2026-09-01; see [status.md](../status.md) for what shipped since
Crate: `pure_math` (Rust). No Python reference exists for this stage.

## 1. Goal

Rank OSRS F2P 1-Defence Combat-Level-30 builds for 1v1 PvP where the build
may carry a second, higher-hitting melee weapon and switch to it for a
knockout. The unit of ranking becomes a **kit**: one resolved survivor row
(account + armour + primary weapon) plus an optional KO weapon.

Stages 1–4 stay untouched and remain byte-for-byte golden against Python.
Stage 5 is additive and consumes their outputs.

## 2. Mechanics this stage relies on

| Rule | Source | How it is used |
|---|---|---|
| A weapon switch costs zero ticks; the remaining attack cooldown carries over; the new weapon's speed applies after its first attack | `rulesets/osrs-f2p-v1/mechanics.json` `weapon.switch`; wiki *Attack speed* | Switch cadence sequence: primary fires at tick 0, KO weapon fires at tick `cd_primary`, then every `cd_ko` |
| Rapid shortbow cooldown = base speed − 1 | `ranged.rapid_attack_cooldown` | Already in `ResolvedStyle.cooldown_ticks` |
| Range→melee stack: shoot a rapid shortbow from 2–3 tiles, switch, melee; both hits ideally land in the same tick and are treated as unreactable | wiki *Free-to-play PvP techniques*, `research/authoritative/f2p-pvp-techniques.json` | Stack KO term, ranged primaries only |
| Melee→melee and range→magic stacks are impractical | same wiki page | No stack term for melee primaries |
| Carried switch items occupy inventory; equipped ammo does not | `src/pure_solver/kits.py`, [architecture.md](../architecture.md) | `switch_slots` formula, food slots |
| Every food eat adds 3 ticks of attack delay | `rulesets/osrs-f2p-v1/consumables.json` | Unchanged Stage 4 race with `eat_penalties=[3,0]` |

Explicitly **not** modelled (declared in the report's scope strings):
distance and movement, projectile flight ticks, PID order, potions, magic
switches, prayer, defence change when the shield is dropped for a 2H,
opponent kits (panel opponents keep their single weapon).

## 3. Inputs

```
pure_math expand-ko-kits <ruleset> <resolved-survivors.csv>
    --screen-report=<resolved-screen-report.json>
    --kits-output=<kits.csv> --report-output=<kits-report.json>
    [--panel-size=32] [--inventory-slots=28] [--heal-per-eat=14]
    [--eat-penalties=3,0] [--preview-size=50]
```

- `<ruleset>` — `mechanics.json` and `items.json`, loaded exactly as Stage 3 does.
- `<resolved-survivors.csv>` — Stage 3 output, loaded with the **existing**
  `ranking::load::load_ranking_candidates` so every survivor becomes a
  `RankingCandidate` with the same validation as Stage 4.
- `--screen-report` — Stage 3 report JSON. Only `representative_defence_rolls`
  is read (`{low|medium|high: {stab,slash,crush,ranged: roll}}`), so the
  stack and switch KO numbers use the same three defence states as the
  existing cadence numbers. Missing or malformed → hard error.
- `--inventory-slots` replaces Stage 4's `--food-slots`: food per kit is
  `inventory_slots − switch_slots`.

## 4. Kit enumeration

For each survivor row `P` (the primary):

1. Account = the row's `account_*` levels. Primary weapon item and optional
   shield item are looked up in `items.json` by id.
2. **Reconstruction check**: armour-only bonuses are computed as
   `row_bonus − primary_weapon_bonus − shield_bonus − ammo_bonus` for the
   `attack_stab/slash/crush/ranged`, `melee_strength`, `ranged_strength`
   columns. Then `armour + primary + shield + ammo` must reproduce the row
   exactly; if it does not, the command fails with the row's candidate id.
   This guards the assumption that the gear-matrix bonus columns are item sums.
3. Candidate KO weapons = items where `is_item_legal(item, account)`,
   `item.is_weapon()`, every damage type in `item.damage_types()` is one of
   `stab|slash|crush`, and `item.item_id != primary weapon id`.
4. KO loadout = armour + KO weapon + ammo (ammo stays equipped) + shield
   only if the KO weapon is one-handed and the primary row had a shield.
   `StyleInputs` for the KO loadout use the account levels, the KO weapon's
   `attack_speed`, `attack_range`, sorted `attack_styles`, and the loadout's
   summed bonuses. Styles are resolved with `CombatKernel::resolve_styles`
   (the same prayers and potion rules as the primary).
5. Keep the KO weapon only if `max(ko.max_hit) > max(primary.max_hit)`.
   A KO weapon that cannot out-hit the primary is not a KO weapon.
6. Every row also emits a **baseline kit** with no KO weapon, so
   single-weapon builds are ranked in the same population.

`switch_slots` = `max(|KO_items \ P_items|, |P_items \ KO_items|)` over item
ids excluding ammo. Baseline = 0. Examples: bow→2H = 1; scim+shield→2H = 2;
scim+shield→mace = 1. `food_slots = inventory_slots − switch_slots`; a
negative result is a hard error.

`kit_id` = `canonical_hash({"candidate_id": P.candidate_id, "ko_weapon_id": id|null})`.

## 5. Kit metrics (all exact `Rational`)

Let `PMF(style, label)` = `DamageDistribution::from_success_chance(accuracy(style.attack_roll, rolls[label][style.damage_type]), style.max_hit, zero_to_one)`, identical to Stage 3.

**Stack KO** (`stack_ko[label:hp]`, 3 labels × 6 HP thresholds `5,10,15,20,25,30`).
Only when the primary's `weapon_type` is `shortbow`, it has a style whose
family is `rapid`, and the kit has a KO weapon. `stack = PMF(rapid style, label) ⊗ PMF(k, label)` maximised over
KO styles `k`; value = `stack.at_least(hp)`. Otherwise every entry is 0.
Reduced for scoring to `stack_ko_by_hp[hp]` = mean over labels, and
`stack_ko_mean` = mean of those six.

**Switch cadence KO** (`switch_ko[label:window:hp]`, windows `4,5,8,12`).
For every primary style `s` and KO style `k` with `cd_s < window`:
`n_k = 1 + (window − 1 − cd_s) / cd_k` (integer division),
`total = PMF(s) ⊗ PMF(k)^{⊗ n_k}`. Also include every no-switch sequence
from Stage 3 (`n = 1 + (window − 1)/cd`, one style repeated). Entry =
max over all sequences of `total.at_least(hp)`. Projectile delay is ignored,
matching the existing cadence scope. Baseline kits reproduce Stage 3's
`cadence_ko_probabilities` exactly. Reduced to `switch_ko_by_window[w]` =
mean over labels and HP thresholds (same reduction as `ko_by_window`).

**KO weapon summary**: `ko_max_hit`, `ko_potted_max_hit`, `ko_attack_roll`
(max over KO styles), `ko_cooldown_ticks` (min), `ko_damage_types`,
`ko_style_ids`. Baseline copies the primary's values.

**Race**: Stage 4's `race_margin` unchanged. Outgoing DPT = `best_dpt` over
the **union** of primary and KO styles versus the opponent's defence roll.
Incoming DPT = opponent's single-weapon `best_dpt` versus the primary's
defence rolls (unchanged). `food_slots` is the kit's value; the opponent's
food stays `inventory_slots` (opponents are single-weapon panel rows with no
switch). Panel = `select_panel` over the survivor candidates exactly as
Stage 4 (size + 1, last entry is the self-matchup reserve). A kit whose
primary is a panel row swaps that mirror for the reserve, as Stage 4 does.

## 6. Scoring and ranking

Population = all kits. Midrank percentiles and category means reuse
`ranking::scores` helpers.

| Category | Metrics (equal weight) | Source |
|---|---|---|
| sustain | `sustained_dpt` low/medium/high | primary (Stage 3) |
| race | robust worst; penalty-3 p10 and mean; penalty-0 mean | kit |
| burst | `ko_by_window` ×4, `max_hit`, `potted_max_hit` | primary |
| defence | 4 defence rolls, magic defence bonus | primary |
| utility | range, style breadth, Prayer level, Prayer bonus, magic attack bonus | primary |
| **ko_switch** | `stack_ko_mean`, `switch_ko_by_window` ×4, `ko_max_hit` | kit |

`overall_score` = mean of the six category percentiles.
Tie-break: `race, ko_switch, burst, sustain, defence, utility, kit_id`.
Tiers: same cutoffs as Stage 4 over the kit count. Niche flags and
simulator-seed reasons are inherited from the primary row.

Consequence to be aware of: melee-primary kits have `stack_ko_mean = 0` and
share the lowest midrank on that one metric. This is intended and reflects
the wiki's statement that only range→melee stacks are practical.

## 7. Outputs

**`kits.csv`** (CRLF, one row per kit, rank order). Columns, in order:

```
rank, tier, kit_id, candidate_id, resolved_signature, is_baseline,
ko_weapon_id, ko_weapon_name, ko_damage_types, ko_style_ids,
ko_max_hit, ko_potted_max_hit, ko_attack_roll, ko_cooldown_ticks,
switch_slots, food_slots,
overall_score, overall_score_decimal,
sustain_score, race_score, burst_score, defence_score, utility_score, ko_switch_score,
race_penalty3_worst_fish, race_penalty3_p10_fish, race_penalty3_mean_fish,
race_penalty0_worst_fish, race_penalty0_mean_fish,
stack_ko_5, stack_ko_10, stack_ko_15, stack_ko_20, stack_ko_25, stack_ko_30,
switch_ko_4_tick, switch_ko_5_tick, switch_ko_8_tick, switch_ko_12_tick,
dpt_low, dpt_medium, dpt_high, ko_4_tick, ko_5_tick, ko_8_tick, ko_12_tick,
maximum_attack_roll, max_hit, potted_max_hit, maximum_range,
defence_stab_roll, defence_slash_roll, defence_crush_roll, defence_ranged_roll,
magic_attack_bonus, magic_defence_bonus, prayer_bonus,
niche_flags, rank_reasons, simulator_seed, simulator_seed_reasons,
profile_id, account_attack, account_strength, account_ranged, account_magic,
account_prayer, account_defence, account_hitpoints,
head_name, neck_name, body_name, legs_name, hands_name, weapon_name,
ammo_name, shield_name, weapon_type, weapon_slot, two_handed,
damage_types, style_ids
```

Fractions are written as `n/d` like Stage 4; booleans as `True`/`False`.
The Stage 3 source columns are **not** appended (the kit population is
several times larger than the survivor population; `candidate_id` joins
back to the survivor manifest).

**`kits-report.json`** (canonical pretty-sorted JSON via `write_json`):
`scope: "ko_kit_priority_ranking_v1"`; a `verification` block with explicit
scope strings for weapon switching, stacking, inventory, and opponents;
`formula` block describing every rule in §5–6; `configuration`; `counts`
(survivor rows, kits, baseline kits, rows with at least one KO option,
tier counts, panel size); the panel with reasons; `top_preview` of the first
`preview_size` kits with the full per-kit document (stack and switch maps
keyed exactly as above).

The CLI prints the `counts` summary plus echoed paths, like Stage 4.

## 8. Code layout (all new, each file under ~300 lines)

```
pure_math/src/kits/mod.rs        types: Kit, KoLoadout, KitMetrics, KitConfig, consts, scope strings
pure_math/src/kits/loadout.rs    armour reconstruction, KO StyleInputs, switch_slots
pure_math/src/kits/enumerate.rs  legal KO weapons per row, baseline kit, kit_id
pure_math/src/kits/ko.rs         stack PMF and switch-cadence table + reductions
pure_math/src/kits/race.rs       union-style outgoing DPT, per-kit food, scenario adapter
pure_math/src/kits/scores.rs     six-category scoring, ordering, tiers
pure_math/src/kits/output.rs     kits.csv + report JSON
pure_math/src/commands/kits.rs   CLI wiring
```

Reused unchanged: `ranking::load`, `ranking::panel::select_panel`,
`ranking::race::{style_dpt, race_margin}`, `ranking::scores::{midrank_percentiles, tier_for}`
(made `pub` where needed), `combat::{CombatKernel, DamageDistribution}`,
`items::{load_items, is_item_legal}`, `canonical`, `io`.

## 9. Error handling

Fail closed with the offending kit or candidate id: unknown item id,
reconstruction mismatch, KO weapon with no resolvable styles, negative food
slots, missing representative roll for a damage type, missing screen
report. No silent skipping of rows.

## 10. Testing

Unit tests (hand-computed rationals):
- `switch_slots` for bow→2H, scim+shield→2H, scim+shield→mace, baseline.
- Stack PMF: two hits with max hits 2 and 3 at known accuracies; assert
  `at_least(hp)` for hp 1..5 against the enumerated joint distribution.
- Switch cadence attack counts: `(window 8, cd_s 3, cd_k 7) → n_k 1`,
  `(8, 3, 4) → 2`, `(4, 4, 7) → no switch sequence`.
- Switch table ≥ Stage 3 cadence table for every key.
- KO weapon filter: excludes ranged and magic weapons, the primary itself,
  and weapons that cannot out-hit the primary.
- Baseline kit reproduces Stage 4: race scenarios identical when
  `inventory_slots = 28`, `switch_ko == cadence_ko`, `stack == 0`.

Integration test: a small fixture manifest plus screen report under
`pure_math/tests/fixtures`, asserting the CSV header, row count
(rows + KO options), rank order determinism, and the report scope string.

Real-data invariant (documented run, not a golden hash): run on
`outputs/cb30-rust/resolved-survivors-cb30.csv`; every baseline kit's five
race columns must equal the Stage 4 ranked CSV's values for the same
candidate id. A script under `pure_math/tests` or the Python `tests/`
tree performs the join and asserts equality.

Performance target: all survivors (about 75k rows, a few KO options each)
in under two minutes release build; rayon over kits as Stage 4 does.

## 11. Out of scope for this stage

Python CLI delegation, README, viewer `builds.json` regeneration, and the
top-30 rerun are separate follow-ups tracked in `docs/status.md`.
