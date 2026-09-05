# Results

These are the headline outputs of the pipeline as of 2026-09-02, collected from the report JSON and logs of each pipeline run (the git-ignored `outputs/` tree) and the viewer datasets exported from them. Every table is a **priority ranking from a closed-form model**, not a simulated or measured win rate: the attrition ranking orders kits by population percentiles of sustained damage, a notional food race, cadence knockout odds, defence and utility; the kill-pressure ranking orders them by the raw probability that their best unanswerable burst beats one 14-heal. Neither ranking models movement, projectile flight, player ordering, prayer switching or an opponent who switches or eats strategically, and the two rankings disagree strongly about which builds are best; [methodology.md](methodology.md) explains why. Numbers are dated because each modelling addition (Strength potion, amulet switch, magic, Defence levels) changed them.

## How to read the tables

- "A/S/R, HP" is Attack / Strength / Ranged and Hitpoints; Defence is 1 unless a Defence column is shown; Magic is whatever fills the combat level.
- "→" separates the primary weapon from the carried KO switch. Every leader shoots a Maple shortbow on rapid (3-tick, adamant arrows) and switches to a warhammer, which needs Strength rather than Attack to wield.
- "Pressure" (also "beats one fish") is `P(arrow + KO hit > 14)` averaged over low, medium and high opponent defence; "max burst" is the largest damage that stack can deal; "race margin" is the penalty-3 mean attrition margin in fish.
- Ranks are positions in the full kit population for that run; the population sizes are in [status.md](status.md) and [pipeline.md](pipeline.md).

## Combat 30 and 40 at 1 Defence: attrition ranking (2026-09-01, before potion, amulet and magic)

| | Combat 30 | Combat 40 |
| --- | --- | --- |
| Kit #1 | Maple shortbow → Adamant warhammer, 20 Atk / 36 Str / 41 Rng / 35 HP | Maple shortbow → Rune warhammer, 25 Atk / 48 Str / 49 Rng / 46 HP |
| Bow max hit / KO max hit | 8 / 9 | 10 / 14 |
| P(arrow + KO ≥ 15) | 5% | 27% |
| P(arrow + KO ≥ 20) | 0% | 7% |
| Best no-switch kit rank | 913 of 918,427 | 3,869 of 1,660,515 |
| Top 1,000 primaries | all shortbows | 916 maple, 84 willow |

## Kill-pressure leaders after potion, amulet and magic (2026-09-02, 1 Defence)

Each addition was re-run for both levels; the leader's pressure rose with the Strength potion and again with the amulet switch, and magic changed nothing at the top.

| | Combat 30 | Combat 40 |
| --- | --- | --- |
| Kill-pressure #1 | 7 Atk / 52 Str / 39 Rng, 44 HP (Magic 39), Maple shortbow → Rune warhammer + Amulet of strength | 21 Atk / 55 Str / 51 Rng, 49 HP (Magic 51), the same kit |
| Pressure | 20.8% | 37.9% |
| Max burst | 23 | 28 |
| Food slots | 25 | 25 |
| Pressure before potion → with potion → with amulet | 15.4% → 20.1% → 20.8% | 31.7% → 36.8% → 37.9% |
| Its runes variant | Fire Bolt (max 12, 3 rune slots), pressure rank 3, 22 food | Water Blast (max 14), pressure rank 2, 22 food |
| Attrition #1 in the same run | (unchanged shape: see the table above) | 22 Atk / 51 Str / 49 Rng, Maple shortbow → Rune warhammer + Amulet of strength; pressure rank 133 (141 before the 2026-09-04 rerun) |
| Kits in the population | 2,335,208 (918,427 before the additions) | 5,365,714 after the 2026-09-04 potted-filter fix (4,349,384 on 2026-09-02; 1,660,515 before the additions) |

The combat-40 column was rerun on 2026-09-04 after the kit stage started comparing potted hits (see [status.md](status.md)): the kill-pressure leader, its pressure, burst, food and runes variant are unchanged, and the attrition leader is the same account; only the population and the ranks around them moved. Combat 30 was not rerun.

Magic does not move kill pressure at these levels because no castable spell beats a 14 heal in one hit (Fire Bolt 12 at 35 Magic, Water Blast 14; Fire Blast 16 needs 59 Magic); it raises finish odds and race DPT only, and each runes variant sits just behind its own kit with three fewer food.

## Combat 40 with Defence opened (2026-09-02)

The catalog was extended to 150 items (metal armour bronze to rune, hardleather, studded, green dragonhide body, staves) and Defence became a real level in the enumerator with its Hitpoints XP and combat-level cost. Every Defence level 1..40 produced 133,467 accounts and 1.36 million survivors and ran out of memory at the kit stage, so the run uses the armour breakpoints 1, 5, 10, 15, 20, 30, 40 with `--max-builds=150000 --max-ko-options=2 --magic=0` (433,845 shortlisted survivors, 1,181,467 kits). Best kit per Defence level, all Maple shortbow → Rune warhammer + Amulet of strength with a Strength potion:

| Defence | Account (A/S/R, HP) | Body | Beats one fish | Max combo | Race margin | Pressure rank |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 29/53/55, 50 | Leather | 23.2% | 27 | 7.4 fish | 1 |
| 5 | 28/53/49, 47 | Leather | 21.4% | 26 | 5.8 | 170 |
| 10 | 23/53/50, 47 | Hardleather | 20.5% | 26 | 8.9 | 673 |
| 15 | 20/53/49, 48 | Hardleather | 19.2% | 26 | 10.6 | 3,053 |
| 20 | 20/52/48, 46 | Studded | 17.2% | 25 | 12.4 | 12,328 |
| 30 | 15/50/42, 43 | Studded | 13.8% | 24 | 12.3 | 39,795 |
| 40 | 13/46/36, 41 | Studded | 9.9% | 22 | 11.3 | 121,676 |

Rerun on 2026-09-04 after the kit stage started comparing potted hits (see [status.md](status.md)): 1,181,467 kits instead of 1,152,628, the same leaders down to 20 Defence with the same pressure, and new leaders at 30 and 40 Defence, where an Amulet of strength swap that only pays off potted (Strength 50 and 46) had been dropped before.

Kill pressure stays with 1 Defence and falls about 3 to 4 points per 10 Defence. The attrition ranking flips to 20 Defence (26 Atk / 43 Str / 46 Rng, 41 HP, studded body, 13-fish margin) and its entire top 10 is 20-Defence accounts. Pressure values are lower than in the 1-Defence-only run (23% versus 38% at the top) because the opponent panel now contains tanks, so every kit is measured against higher defence rolls. Rune armour never reaches the top of either ranking: every top kit is an archer, and metal armour costs ranged accuracy. Rune matters only for melee-primary tanks, none of which reached the top.

Mage pures are absent from this run by construction: the account frontier compares accounts on Attack, Strength, Ranged, Prayer and Hitpoints and treats Magic as filler, so a 1 Attack / 1 Strength / 1 Ranged / 10 HP / 76 Magic account (combat 40 with Fire Blast, 16 max) is pruned before any gear is attached. See [status.md](status.md).

## What the two rankings disagree about (2026-09-01, 1 Defence, before potion, amulet and magic)

| | Combat 30 | Combat 40 |
| --- | --- | --- |
| Attrition #1 | 20 Atk / 36 Str / 41 Rng / 35 HP, Maple shortbow → Adamant warhammer (max 9) | 25 Atk / 48 Str / 49 Rng / 46 HP, Maple shortbow → Rune warhammer (max 14) |
| … its pressure | 5%, pressure rank 2,304 | 27%, pressure rank 679 |
| Kill-pressure #1 | 8 Atk / 50 Str / 38 Rng / 41 HP, Maple shortbow → Rune warhammer (max 14) | 16 Atk / 63 Str / 52 Rng / 54 HP, Maple shortbow → Rune warhammer (max 17) |
| … its pressure / bite / finish@15 | 15%, +0.45 HP, 15% | 32%, +1.49 HP, 32% |
| … its attrition rank | 14,924 | 4,341 |
| Kits with any pressure | 16,962 of 918,427 | 212,881 of 1,660,515 |

Attrition wants Attack for accuracy and Ranged for chip; kill pressure dumps Strength with near-zero Attack so a Strength-only Rune warhammer hits 14 to 17 on a 41 to 54 HP account. The pressure shape is the archetype experienced F2P pures actually build.

## Two findings worth keeping

1. **Warhammers need Strength, not Attack.** A 7-Attack, 52-Strength pure (the combat-30 leader) gets a Rune warhammer switch without spending combat level on Attack; the math found that on its own, and every leader in every table above is a shortbow-to-warhammer kit on a low-Attack, high-Strength account.
2. **The best single-weapon build cannot switch.** The best single-weapon build at combat 30 (22 Atk / 16 Str / 40 Rng) has nothing it can switch to, which is why it falls from build rank 1 to kit rank 913 once kits are ranked together.

## How to reproduce

Build the Rust binary and run [`pure_math/scripts/run_pipeline.ps1`](../pure_math/scripts/run_pipeline.ps1) (or `run_pipeline.sh`) with `-CombatLevel 30 -DefenceLevels '1'` or `-CombatLevel 40 -DefenceLevels '1,5,10,15,20,30,40'`; the Defence-opened figures also need `run_stages.ps1 -Stages 5 -MaxBuilds 150000 -MaxKoOptions 2 -Magic 0`. Stage-by-stage commands, flags, output files and the viewer export are in [pipeline.md](pipeline.md). Because every stage is exact rational arithmetic, a rerun on the same ruleset produces byte-identical CSVs; a different ruleset revision (new items, new decisions) will not, and the report JSON records which one was used.
