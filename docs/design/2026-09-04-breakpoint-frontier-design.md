# Stage 1b: breakpoint account frontier (`breakpoint-frontier`) design

Date: 2026-09-04
Status: design; implementation tracked in [status.md](../status.md)
Lane: `pure_solver` (Python). Stages 2 to 5 of `pure_math` consume the output unchanged.

## 1. Goal

Replace the exhaustive Stage 1 enumeration with a generator that emits only the accounts
that can win, derived from the formulas instead of tried one by one, and prove on the
combat-40, 1-Defence population that nothing at the top is lost.

Stage 1 today walks every Attack/Strength/Ranged/Prayer/Hitpoints split at the target
combat level (4,065,498 raw states at combat 40) and keeps a Pareto frontier (3,977
ranking accounts). The frontier is exact but blind to what the later stages value: it
keeps Strength 54 next to Strength 53 although no F2P weapon hits harder at 54, and it
keeps every reachable Hitpoints level although only the lowest matters for a knockout.
The cost is not the minute it takes at combat 40; it is that the same walk over Defence
1 to 40 produces 133,467 accounts and runs the kit stage out of memory, and that every
new combat level is a fresh multi-gigabyte run.

The breakpoint frontier makes the account count scale with the number of formula
breakpoints rather than with the level ranges, so a sweep over combat levels or an
opened Defence axis stays small.

## 2. Why the winners sit on breakpoints

Every quantity the fight math reads from an account is monotone in the levels, and the
levels enter through a few pinned formulas (`rulesets/osrs-f2p-v1/mechanics.json`):

| Quantity | Formula | Shape in the level |
| --- | --- | --- |
| Combat level | `combat_level`: floor of a quarter of (Defence + Hitpoints + floor(Prayer/2)) plus 0.325 times the largest of Attack + Strength, floor(1.5 Ranged), floor(1.5 Magic) | Linear plane per regime; the switch between regimes is a corner |
| Melee max hit | `melee.effective_strength` then `melee.max_hit`: floor((effective strength times (bonus + 64) + 320) / 640) | Staircase in Strength; the step positions depend on the strength bonus, the prayer multiplier, the style bonus and the potion boost |
| Ranged max hit | `ranged.effective_strength` then `ranged.max_hit` | Staircase in Ranged; steps depend on the ammunition's ranged strength, prayer and style |
| Attack rolls | `melee.attack_roll`, `ranged.attack_roll` | Smooth in Attack or Ranged: every level helps a little |
| Prayer multipliers | `prayer.f2p.*_boosts` | Step function on the verified prayer levels |
| Item legality | item `requirements` | Step function on the requirement levels |
| Hitpoints | `experience.level_threshold` and the standard-training damage range | A reachable interval per Attack/Strength/Ranged triple |

Consequences, each visible in the combat-40 kit rankings:

- Strength between two max-hit steps is wasted combat level. With the potted Rune
  warhammer and Amulet of strength at Prayer 13 the steps sit at 40, 44, 49, 53, 58, 61,
  66 and 70; the kill-pressure leader is Strength 53, and 54 ranks below it.
- Because accuracy is smooth, whatever combat level is left after Strength goes to
  Attack (or, on the ranged side, to Ranged up to its tie). Along Attack + Strength = 82 at
  Hitpoints 50 the kits read 28/54 at 22.9%, 29/53 at 23.2%, 33/49 at 19.9%.
- Ranged is free until floor(1.5 Ranged) equals Attack + Strength, so the best Ranged
  for a melee-dominant account is exactly the tie (55 when Attack + Strength = 82).
- Prayer only matters on its breakpoints, lifted to the odd level that costs the same
  combat (`prayer_level_choices`).
- Hitpoints only matter at the ends of the reachable interval: the lowest for offence,
  the highest for the attrition ranking.

So the candidate set is the cross product of breakpoints, with the smooth skills filled
from the remainder, not the cross product of level ranges.

## 3. Scope of this version

- 1 Defence only. The Python account model (`accounts.AccountState`) rejects any other
  Defence level and the Hitpoints helpers do not count Defence experience; the Rust port
  has both. Opening Defence is follow-up 1 in section 10.
- Any combat level from 3 to 126. The generator is not tied to 30 or 40.
- The F2P ruleset as it stands. Members items, and magic as a kit option, are out of
  scope; Stage 5 is run with `--magic=0` for the validation.
- No change to Stages 2 to 5 or to any ranking formula. The generator only decides which
  accounts enter Stage 2.

## 4. Candidate generation

Module `src/pure_solver/breakpoints.py` (threshold tables) and
`src/pure_solver/breakpoint_frontier.py` (assembly and output). Every formula is
evaluated through `formula.evaluate` on the mechanic's pinned expression tree, never
re-typed in Python.

### 4.1 Threshold tables

**Strength.** For every melee weapon in the catalog (an item in the weapon or 2h slot
whose attack styles include a melee style) and every amulet in the catalog, the melee strength
bonus is the sum of the two plus the largest melee strength bonus available in every
other worn slot (zero in F2P, computed from the catalog rather than assumed). The set of
distinct bonus values is the set of bonus classes. For each bonus class, each verified
Strength prayer multiplier (plus 1 for no prayer), each style strength bonus from
`combat_style.f2p_bonuses`, and the Strength potion on or off (`strength_potion.boost`),
scan Strength 1 to 99 with `melee.effective_strength` and `melee.max_hit` and record
the lowest level at which each distinct max hit first appears. The union over all
combinations, plus every Strength requirement in the catalog, is the Strength threshold
set.

**Ranged.** The same scan over Ranged 1 to 99 with `ranged.effective_strength` and
`ranged.max_hit`, with bonus classes from the ammunition's ranged strength (plus the
largest ranged strength in every other slot), the verified Ranged prayer multipliers,
and the style range bonus. The union, plus every Ranged requirement, is the Ranged
threshold set.

**Attack.** Attack has no staircase, so its only thresholds are the Attack requirements
in the catalog. They are used in section 4.2 as an alternative to the remainder rule, so
that a gate one level above the remainder is not missed.

**Prayer.** `account_frontier.prayer_level_choices`.

The report lists every table with the (bonus class, prayer, style, potion) combination
it came from, which is the human-readable answer to "why does the winner sit at 53".

### 4.2 Assembly

For each prayer level, each Strength threshold and each Ranged value in the Ranged
threshold set:

1. Attack is the largest level from 99 down to 1 at which the account fits under the
   combat level with Magic 1 and its lowest reachable Hitpoints. Hitpoints depend on
   Attack through training experience, so each probe takes the lowest level of
   `experience.standard_f2p_hitpoints_levels` for that Attack, Strength and Ranged.
   Combat level is monotone in Attack, so the scan stops at the first fit.
2. With Attack fixed, the Hitpoints candidates are that lowest reachable level and the
   highest reachable level that still fits (`combat_level_hitpoints_interval` bounds the
   fit; the reachable levels bound the training).
3. The Ranged tie for this Attack + Strength (the largest Ranged with floor(1.5 Ranged)
   at most Attack + Strength) is assembled as an extra Ranged value for the same prayer
   and Strength. Its extra Ranged experience can lower the lowest reachable Hitpoints or
   push Attack down by one, so steps 1 and 2 run again for the tie until Attack and the
   tie stop moving (two or three passes).
4. Magic is filled with `account_frontier.maximum_magic_for_combat`; an account that
   cannot reach the combat level exactly is dropped.
5. The mirror pass: for each Attack requirement level in the catalog as a fixed Attack,
   Strength is the remainder found the same way, so a weapon gate one level above the
   remainder is represented.

Every account is checked with `AccountState.combat_level` against the pinned formula
before it is kept, as Stage 1 does. Duplicates are removed. By default the set is then
reduced with `account_frontier.pareto_frontier(ignore_magic=True)` so the output is a
subset of what Stage 1 would keep; `--no-pareto` keeps every generated account.

### 4.3 Command and outputs

```text
python -m pure_solver breakpoint-frontier <ruleset>
    --combat-level=40
    --ranking-output=<accounts-ranking.csv>
    --report-output=<breakpoint-frontier.json>
    [--no-potion] [--no-pareto]
```

`accounts-ranking.csv` uses `account_frontier.write_account_frontier_csv`, so it is
byte-compatible with Stage 1 output and Stage 2 reads it as is. The report JSON carries
`combat_level`, `defence_level`, the prayer levels, the Strength and Ranged threshold
tables, the Attack gates, `counts` (`generated`, `after_pareto`, `strength_thresholds`,
`ranged_thresholds`) and the scope strings from section 3.

## 5. Running the later stages on it

`pure_math/scripts/run_stages.ps1` and `run_pipeline.ps1` gain an `-OutDir` parameter
whose default is the current `outputs\cb<level>-rust`, so a breakpoint run writes to its
own folder and can never overwrite a full run:

```powershell
$env:PYTHONPATH = 'src'
python -m pure_solver breakpoint-frontier rulesets/osrs-f2p-v1 --combat-level 40 `
    --ranking-output outputs/cb40-breakpoints/accounts-ranking.csv `
    --report-output outputs/cb40-breakpoints/breakpoint-frontier.json
powershell -File pure_math\scripts\run_stages.ps1 -CombatLevel 40 -OutDir outputs\cb40-breakpoints -Magic 0
```

`pure_math/scripts/run_breakpoints.ps1 -CombatLevels 30,35,40,45` runs the pair above
once per level into `outputs\cb<level>-breakpoints`. Each run has its own opponent panel
and defence quantiles, so kill-pressure values are comparable within a run, not across
runs; that is the same caveat every existing run carries.

## 6. Validation

Module `src/pure_solver/breakpoint_validation.py`, command `validate-breakpoints`.

Comparing a breakpoint run's numbers with a full run's numbers would confound the
generator with the panel, because Stage 4 draws the opponent panel and the defence
quantiles from the population. The check therefore happens inside one full run: does
the breakpoint set contain the accounts the full run ranks at the top?

```text
python -m pure_solver validate-breakpoints
    --breakpoint-accounts <accounts-ranking.csv>
    --full-accounts <accounts-ranking.csv of the full run>
    --full-kits <kits-cbNN.csv of the full run>
    [--top=22] [--report-output=<validation.json>]
```

It streams the kits CSV once with the standard library, keeps the rows whose
`pressure_rank` is at most `--top`, skips rows with a `spell_name`, and for every
(primary weapon, KO weapon) pair records the best `kill_pressure` among kits whose
account is in the breakpoint set. The report states, per top kit, the account, the pair,
the kill pressure, and the covering breakpoint kit (equal or better kill pressure on the
same pair) or `null`; plus `top1_covered`, `uncovered` (the list of misses), and coverage
counts (full frontier accounts, breakpoint accounts, and the intersection). The command
exits 1 when the top kit is uncovered or any top-N kit is uncovered, so it can gate.

The full run used for the first validation is combat 40, 1 Defence, Stage 5 with
`--magic=0`, written to `outputs\cb40-1def-nomagic` from the existing Stage 3 outputs in
`outputs\cb40-rust-1def` (Stage 5 only, a few minutes). A miss means a breakpoint is
missing from section 4.1 and is fixed there before the generator is used anywhere else.

## 7. Tests

`tests/test_breakpoints.py`, `tests/test_breakpoint_frontier.py`,
`tests/test_breakpoint_validation.py`, unittest style like the rest of `tests/`:

- The Strength scan for bonus class Rune warhammer plus Amulet of strength at Prayer 13,
  aggressive, potted, yields 53 as the first level with max hit 17 and 58 for 18.
- Every threshold scan agrees with a direct evaluation of the same mechanics at the
  levels on either side of each step (the step is real, the level below it is not).
- The assembled account 29/53/55 at combat 40 has Hitpoints 50 as its lowest reachable
  level and Magic 55 after fill, and appears in the generated set.
- Every generated account is in `enumerate_exact_combat_accounts` for the same level
  (legality against the exhaustive universe, checked on a small combat level to keep
  the test fast).
- The CSV written has exactly Stage 1's header and reads back through
  `read_account_frontier_csv`.
- Validation on a ten-row kits fixture: a covered top kit, an uncovered one, a runes
  variant that is skipped, and the exit code.

## 8. Documentation

- [pipeline.md](../pipeline.md): a "Stage 1b: `breakpoint-frontier`" section after
  Stage 1 with the command, flags, outputs and the validation command, and the
  `-OutDir` parameter in the wrapper-script section.
- [status.md](../status.md): a Done row with the measured counts and the validation
  result, and a known-gap row for Defence.
- [README.md](../../README.md): one paragraph under "Run the search yourself" naming the
  breakpoint run as the small way to get a ranking for another combat level.

## 9. Expected outcome and success criteria

Measured, not assumed, and written into status.md:

| | Full Stage 1 | Breakpoint frontier (expected) |
| --- | --- | --- |
| Accounts at combat 40, 1 Defence | 3,977 | 1,000 to 2,000 |
| Stage 1 runtime | seconds | seconds |
| Stages 2 to 5 at combat 40, no magic | about 5 minutes | about a minute |
| Another combat level | a full rerun of the same size | one small run |

Success: the validation report has `top1_covered: true` and an empty `uncovered` list
for the top 22 at combat 40, and every generated account is legal. Anything else is a
finding to run down on both sides before either is trusted: a missing breakpoint in
section 4.1, or a ranking formula in Stages 3 to 5 that rewards a level the pinned
mechanics say cannot matter. The design is not considered working until the miss is
explained and fixed where the fault is.

## 10. Follow-ups, not in this version

1. **Defence as an axis.** Either lift the 1-Defence restriction in
   `accounts.AccountState` and add Defence experience to the Hitpoints helpers (mirroring
   `pure_math/src/experience.rs`), or port the generator to Rust next to
   `account_frontier.rs`. Defence thresholds are the armour requirement levels.
2. **A fixed reference panel.** Let Stage 4 and 5 read the panel and defence quantiles
   from a saved report so runs at different levels or populations produce comparable
   kill-pressure numbers.
3. **Magic thresholds.** Spell unlock levels as Magic breakpoints, for when mage pures
   enter the frontier.
4. **Members catalog.** Nothing in the generator is F2P-specific; it needs verified items.
