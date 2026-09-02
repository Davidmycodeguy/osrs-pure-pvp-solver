# Methodology

The solver answers one question with exact arithmetic: given every legal account at an exact combat level and every legal free-to-play item, which combination of levels, worn gear and carried switch is the best 1v1 PvP build? It does not simulate fights. Each build is reduced to closed-form quantities computed from exact damage distributions (sustained damage per tick, knockout probabilities inside short windows, a notional attrition race against a diverse opponent panel, and a kill-pressure measure), and builds are ordered by population percentiles of those quantities. This page states the question, the decision variables, every mechanic the model encodes with its formula, the per-kit outputs and their definitions, how the opponent panel is chosen, how percentiles and tiers are formed, the kill-pressure ranking, why the two rankings disagree, and the limits the reports declare. Formulas are written as the ruleset stores them; the game-mechanics prose restates the pinned wiki mechanics the ruleset cites.

## The question

Given every legal account (skill levels combining to an exact combat level, Defence fixed at 1 or drawn from a chosen list) and every legal free-to-play item, which combination of levels, worn gear and carried weapon switch wins the most 1v1 fights?

Constraints that matter: with 1 Defence, armour is limited to leather-tier and a few special items; free-to-play has no special attacks, so the only "knockout" tool is switching to a slower, harder-hitting weapon; 28 inventory slots are shared between food and switches; a game tick is 0.6 seconds and every timer below is in ticks.

## Decision variables

| Variable | Domain | Constraint |
| --- | --- | --- |
| Attack, Strength, Ranged, Prayer, Hitpoints, Magic | 1–99 each | The pinned combat-level formula must give exactly the target level. Hitpoints must be reachable by standard F2P combat training of Attack, Strength, Ranged and Defence (4 XP per damage to the trained skill, 4/3 XP to Hitpoints). Prayer sits on a verified prayer breakpoint, lifted to the odd level that costs the same combat. Magic is filled to the highest level that keeps the combat level exact and is otherwise treated as leftover. |
| Defence | 1 (classic pure), or a list such as 1, 5, 10, 15, 20, 30, 40 | Costs combat level and Hitpoints XP like any trained skill; gates metal armour. |
| Worn gear | head, neck, body, legs, hands, weapon, ammo, shield from the 150 verified items | Must be legal for the account (skill and quest requirements, F2P, obtainable); dominated items are pruned per account; armour is the offence Pareto set per weapon (Stage 2). |
| Attack style | Each weapon's verified styles (accurate, aggressive, controlled, defensive, rapid, longrange) | Every style is resolved; each metric takes the best style. |
| KO weapon (Stage 5) | Any legal melee weapon whose max hit beats the primary's | Costs inventory slots; the baseline no-switch kit is always kept. |
| Amulet switch (Stage 5) | The legal amulet with the highest melee strength bonus | Kept only when it raises the KO max hit; one more slot. |
| Strength potion (Stage 5) | 0 or more carried, default 1 | One slot each. |
| Spell (Stage 5) | The hardest castable F2P spell that out-hits the primary weapon | One slot per distinct rune type (cast bare-handed). |

Not a decision variable: the strongest offensive prayer the account's Prayer level unlocks is assumed active as a multiplier for every roll; prayer drain, flicking and protection prayers are not modelled.

## Encoded mechanics

Every formula is a pinned AST in [`rulesets/osrs-f2p-v1/mechanics.json`](../rulesets/osrs-f2p-v1/mechanics.json), evaluated in exact rationals so every `floor` lands exactly where the source says. The mechanic ids in the table are the keys of that file.

| Mechanic | Rule as encoded | Mechanic ids |
| --- | --- | --- |
| Effective level | `floor((level + boost) × prayer_multiplier) + style_bonus + 8` for Attack, Strength, Ranged, Magic and Defence. | `melee.effective_attack`, `melee.effective_strength`, `ranged.effective_attack`, `ranged.effective_strength`, `magic.effective_attack`, `player.effective_defence` |
| Attack and defence rolls | `A = effective_attack × (attack_bonus + 64)`; `D = effective_defence × (defence_bonus + 64)`. Defence rolls in the pipeline use no boost and no prayer. | `melee.attack_roll`, `ranged.attack_roll`, `magic.attack_roll`, `player.defence_roll` |
| Accuracy | Hit chance is `1 − (D+2)/(2(A+1))` when `A > D`, else `A/(2(D+1))`. Standard OSRS formula; the same function serves melee and ranged. | `melee.accuracy` |
| Damage | On a hit, uniform over 0..max hit; a successful 0 becomes 1 in PvP. Max hit from Strength (or Ranged) and gear via the wiki formula: melee and ranged `floor((effective_strength × (strength_bonus + 64) + 320) / 640)`; magic `floor(base_max_hit × (100 + magic_damage_percent) / 100)`. | `melee.max_hit`, `ranged.max_hit`, `magic.max_hit`, `damage.player_successful_zero_to_one` |
| Style bonuses | accurate +3 attack; aggressive +3 strength; controlled +1 attack/strength/defence; defensive +3 defence; longrange +3 defence and +2 range; rapid nothing. | `combat_style.f2p_bonuses` |
| Speed | Weapon attack speed in ticks; rapid style on bows is one tick faster (`base − 1`). Scimitar 4, warhammer 6, 2H 7, maple shortbow rapid 3. | `ranged.rapid_attack_cooldown`, item `attack_speed` |
| Switching | Zero ticks to switch; the remaining cooldown carries over; the new weapon's speed applies after it fires. Verified against the wiki and an engine source. | `weapon.switch` |
| Eating | A fish heals 14 and adds a 3-tick attack delay. Pizza heals 9 per half with a 1-tick then 2-tick eat delay. Potions add no attack delay (the 3-tick drink delay is not modelled in the pipeline). | `food.swordfish`, `food.anchovy_pizza`, `potion.drink_delay_ticks` |
| Inventory | A carried switch costs one slot per item not shared between the two loadouts; equipped ammo is free. A 2H switch on a shield user costs 2. `switch_slots = max(|KO ∖ P|, |P ∖ KO|) + 1 if the amulet is swapped`, over weapon and shield ids. | `manifest.json` `inventory_slots` |
| Strength potion | Boost `3 + floor(Strength / 10)`; melee hits in the stack, switch-cadence and kill-pressure tables use the potted max hit; the race keeps unpotted DPT; ranged and magic hits are unaffected. | `strength_potion.boost` |
| Amulet switch | Each KO weapon is also tried with the Amulet of strength swapped in (+10 melee strength versus +6 on the Amulet of power) when that raises the KO max hit. | `items.json` neck records |
| Magic | Spells from the verified spell table (5-tick cast, level, rune cost): Fire Bolt 12 at 35 Magic, Wind Blast 13 at 41, Fire Blast 16 at 59. Effective attack with no boost, no style bonus and the best F2P magic prayer; attack roll with the worn gear's magic attack bonus. Cast bare-handed: the four elemental staves in the catalog are modelled as bash weapons with no spell support, so each rune type costs one slot. | `magic.f2p.spells`, `magic.effective_attack`, `magic.attack_roll`, `magic.max_hit` |
| Opponent magic defence | `(floor(0.7 × (Magic + 8)) + floor(0.3 × (Defence + 8))) × (magic_defence_bonus + 64)`. The standard 70% Magic / 30% Defence rule; **not** a verified ruleset mechanic and reported as `magic.defence_roll_unverified`. | none |
| Representative defence | Every KO and DPT table is evaluated against three defence states, low / medium / high, the 1/10, 1/2 and 9/10 quantiles of the survivor population's defence rolls per damage type (Stage 3) and of the magic defence rolls (Stage 5). | Stage 3 report `representative_defence_rolls` |

## Per-kit outputs

Every hit is kept as a full probability distribution, not an average. Two hits are combined by convolution, so "chance the stack totals at least 15" is exact and includes every lucky combination. Let `PMF(s, d)` be the damage distribution of one attack with style `s` against defence state `d`, `cd_s` its cooldown, and `⊗` convolution.

| Output | Definition | Used for |
| --- | --- | --- |
| Sustained DPT | hit chance × expected damage ÷ speed, against low/medium/high defence rolls. With the successful-zero-to-one rule the expected successful damage is `max_hit/2 + 1/(max_hit+1)`, so `DPT = p_hit × (max_hit/2 + 1/(max_hit+1)) / cd`. | sustain score, race |
| Cadence KO | `P(total damage in a 4/5/8/12-tick window ≥ 5..30 HP)`, one weapon repeated: `n = 1 + floor((window − 1) / cd)` attacks, `PMF^{⊗n}`, best style per cell. | burst score |
| Stack KO | `P(one rapid arrow + one KO hit ≥ 5..30 HP)` = `(PMF(rapid) ⊗ PMF(k)).at_least(hp)` maximised over KO styles `k`; shortbow primaries with a rapid style only, zero otherwise. | ko_switch score |
| Switch cadence KO | Same windows, but the KO weapon fires once the carried cooldown expires: for primary style `s` and KO style `k` with `cd_s < window`, `n_k = 1 + (window − 1 − cd_s) div cd_k` and `total = PMF(s) ⊗ PMF(k)^{⊗ n_k}`; every no-switch sequence is included too; entry = max over sequences. Baseline kits reproduce Stage 3's cadence table exactly. | ko_switch score |
| Race margin | Closed-form attrition: each side's DPT is reduced by eat downtime, `uptime = 14 / (14 + 3 × incoming DPT)`; time to kill = `(HP + food × 14) ÷ effective DPT`; margin = the signed extra survival time multiplied by the loser's effective DPT, reported in fish (units of one 14-heal). Kit food = `28 − switch slots − potions − rune slots`; the opponent keeps 28. Run at eat penalty 3 (primary) and 0 (sensitivity). Outgoing DPT is the best over the union of primary, KO and spell styles; incoming DPT is the opponent's single weapon against the primary's defence rolls. | race score |
| Kill pressure | `P(best unanswerable burst > 14)`, expected overshoot, `P(burst ≥ 10/15/20)`; see below. | pressure rank |

Per-window and per-threshold tables are reduced for scoring by taking the mean over the three defence states (and, for switch cadence, over the six HP thresholds).

## Opponent panel

Opponents are a panel of 32 diverse single-weapon survivors chosen by farthest-point sampling ([`ranking/panel.rs`](../pure_math/src/ranking/panel.rs)):

1. Forced extremes: the best survivor on each of ten metrics (average and worst sustained DPT, 4-tick and 12-tick cadence KO, potted max hit, physical defence, magic defence bonus, magic attack bonus, range, prayer bonus).
2. One representative per damage type (stab, slash, crush, ranged) and per weapon type, each the best sustained DPT among eligible rows, so ranged and crush/stab counters stay in the seed set even when melee dominates the population.
3. Farthest-point fill: every survivor becomes a vector of integer midranks over its feature set (DPT triple, four cadence-KO windows, max hit, potted max hit, range, physical defence, magic bonuses, prayer bonus); the row with the largest squared distance to the panel so far is added until the panel is full.

The panel is selected with one extra row, a reserve, so that a survivor who is itself on the panel faces the reserve instead of its mirror and every candidate meets the same number of distinct opponents. Stage 5 reuses the panel exactly as Stage 4 chose it; panel opponents keep their single weapon and full food.

## Percentile scoring and tiers

Scores are population midrank percentiles ("what fraction of kits does this beat on this metric"): with the population sorted, a value's midrank is `bisect_left + bisect_right − 1`, scaled by `2(N − 1)` so ties share the midpoint and the range is 0..1. Metrics are averaged per category, then categories are averaged with equal weight.

| Category | Metrics (equal weight within the category) | Source |
| --- | --- | --- |
| sustain | sustained DPT against low, medium and high defence | primary weapon |
| race | robust worst margin (min over both eat penalties), penalty-3 p10 and mean, penalty-0 mean | build (Stage 4) or kit (Stage 5) |
| burst | cadence KO in 4/5/8/12-tick windows, max hit, potted max hit | primary weapon |
| defence | stab, slash, crush and ranged defence rolls; magic defence bonus | primary loadout |
| utility | range, style breadth, Prayer level, prayer bonus, magic attack bonus | primary loadout |
| ko_switch (Stage 5 only) | stack KO mean, switch-cadence KO for the four windows, KO max hit | kit |

Overall score is the mean of the five (Stage 4) or six (Stage 5) category percentiles. Ties break on race, then (Stage 5) ko_switch, then burst, sustain, defence, utility, then the candidate or kit id. Tiers are cut on rank over the population: S is the top 1%, A to 5%, B to 20%, N is a lower-ranked row that is a panel member or carries a top-1% niche flag (`sustain_extreme`, `four_tick_ko_extreme`, `twelve_tick_ko_extreme`, `potted_max_hit_extreme`, `physical_defence_extreme`, `magic_defence_extreme`, `magic_attack_gear_extreme`, `range_extreme`, or a damage-type representative), C is the remainder. Every row also gets `rank_reasons` naming its two strongest categories.

A consequence to know: melee-primary kits have a stack term of zero and share the lowest midrank on that metric, and baseline kits get a zero stack term inside `ko_switch`, so no-switch kits rank low by construction in the attrition ranking (the best baseline kit at combat 30 sat at rank 913 of 918,427 in the 2026-09-01 run).

## The kill-pressure ranking

A second ranking, reported alongside the first rather than blended into it, uses raw probabilities from the same distributions:

```text
burst      = arrow ⊗ KO hit          (rapid shortbow kit)
           = single hardest hit       (otherwise)
pressure   = P(burst > 14)            "beats one fish"
bite       = E[max(burst − 14, 0)]    expected damage past the heal
finish_h   = P(burst ≥ h)   h ∈ {10, 15, 20}
pressure_rank: sort by pressure desc, bite desc, race margin desc
```

Details as implemented in [`kits/ko.rs`](../pure_math/src/kits/ko.rs) and [`kits/scores.rs`](../pure_math/src/kits/scores.rs): the burst candidates are the arrow convolved with each KO style (plus the spell as a single hit) for a rapid-shortbow kit, otherwise every primary, KO and spell style as a single hit; the candidate with the highest pressure (then finish odds) is kept; every value is averaged over the three defence states; melee hits use the potted max hit when a potion is carried; `max_burst` is the largest damage that burst can deal; and `pressure_rank` breaks ties on the penalty-3 mean race margin and then the kit id. There is no magic-to-melee stack. A no-switch archer at combat 30 scores 0 pressure, which matches how people play. This is a diagnostic, not a solution: it still has no opponent policy and no notion of when the fight is in a kill window.

## Why the two rankings disagree

**The attrition model scores a patient slap fight, not a PvP fight.** Four of the six categories are attrition. The race formula assumes both players eat perfectly on time and that every eat fully works. In that world a knockout weapon is a rounding error, so a build that can never end a fight can sit in the top 0.1%.

Why real players carry a KO weapon, in the model's own terms:

1. **Threat forces early eats.** If your best unanswerable burst can deal 17, a competent opponent must eat at 18 HP instead of 9. Every eat costs 3 ticks of attacks. The switch wins the attrition race indirectly, by raising the opponent's safe-HP threshold. The race formula has no threshold, so it cannot see this.
2. **The finish.** After eating, the opponent is eat-locked for 3 ticks. Damage landing inside that window is unanswerable. If it exceeds their HP, the fight ends. The model has no "eat-locked at HP h" state.
3. **Running.** Fights are not to the death. Without kill pressure the losing side just leaves. So "wins the long race" is not the quantity that decides real outcomes; "can force a mistake" is.

The cliff that makes this level-dependent: one fish heals 14. At combat 30 the attrition winner's stack beats 14 about 5% of the time (the best stack in that run manages 15%), so eating on time is close to sufficient and almost nobody can be punished. At 40 the same two figures are 27% and 32%. The KO weapon goes from decorative to decisive between those two levels, and a scoring built on percentiles cannot express "27% is a real threat, 5% is not". (Those two figures are from the 2026-09-01 run without potion or amulet; with both carried the leaders reach 20.8% at combat 30 and 37.9% at 40.)

Secondary distortions: utility (range, Prayer level, magic attack bonus) carries the same weight as KO; many top accounts carry 40 Magic purely because the combat-level formula lets it fill space, and nothing in the attrition model uses it. The KO-switch category is a percentile of the stack odds, so "has any stack at all" beats 98% of kits regardless of how weak the stack is.

What the two orderings say about the same kits (2026-09-01 run, 1 Defence, before potion, amulet and magic):

| | Combat 30 | Combat 40 |
| --- | --- | --- |
| Attrition #1 | 20 Atk / 36 Str / 41 Rng / 35 HP, Maple shortbow → Adamant warhammer (max 9) | 25 Atk / 48 Str / 49 Rng / 46 HP, Maple shortbow → Rune warhammer (max 14) |
| … its pressure | 5%, pressure rank 2,304 | 27%, pressure rank 679 |
| Kill-pressure #1 | 8 Atk / 50 Str / 38 Rng / 41 HP, Maple shortbow → Rune warhammer (max 14) | 16 Atk / 63 Str / 52 Rng / 54 HP, Maple shortbow → Rune warhammer (max 17) |
| … its pressure / bite / finish@15 | 15%, +0.45 HP, 15% | 32%, +1.49 HP, 32% |
| … its attrition rank | 14,924 | 4,341 |
| Kits with any pressure | 16,962 of 918,427 | 212,881 of 1,660,515 |

The two orderings disagree by four orders of magnitude on the same kits. Attrition wants Attack for accuracy and Ranged for chip; kill pressure dumps Strength (50 at combat 30, 63 at 40) with near-zero Attack so a Strength-only Rune warhammer hits 14 to 17 on a 41 to 54 HP account. Warhammers need Strength rather than Attack to wield, which is why low-Attack, high-Strength pures win the pressure ranking. That second shape is the archetype experienced F2P pures actually build, which is evidence the pressure primitive is pointing the right way even though it is still crude. The dated leader tables after potion, amulet and magic are in [results.md](results.md).

## Declared limits

Every report carries these in its `verification` block; they are restated here so a number is never read without them.

| Limit | Where it applies |
| --- | --- |
| No distance or movement, no projectile flight ticks, no PID (player ordering). The range-to-melee stack is treated as unreactable and same-tick. | Stages 3–5 |
| No prayer in kits: offensive prayers are a fixed multiplier; drain, flicking, protection and prayer switching are absent. | all stages |
| No shield loss on a 2H switch: the KO loadout's defence is not re-evaluated when the shield is dropped. | Stage 5 |
| Panel opponents are single-weapon with full food; they never switch, cast, or change policy. | Stages 4–5 |
| Opponent magic defence uses the standard 70/30 rule, flagged as unverified. | Stage 5 magic |
| No magic-to-melee stack; the stack term exists only for rapid shortbow primaries. | Stage 5 |
| Staves carry no spell support (the catalog models them as bash weapons), so spells are costed bare-handed (three rune slots for a bolt where a staff would make it two) and get no staff magic bonus. | Stage 5 magic |
| No cape, boots or ring slots; shields limited to the catalog's offensive shield and, with `--keep-defensive`, the most defensive legal shield. | Stage 2 |
| Mage pures are pruned by the account frontier because Magic is not a compared skill. | Stage 1 |
| Every ranking is a priority order from a closed-form model, labelled `heuristic_priority_order_only`, with `production_ready: false` and `perfect_play_claim: false`. | Stages 4–5 |

## Toward a duel solve

The intended fix for the attrition bias is to solve the duel instead of scoring features: a tick-level Markov game with state (my HP, their HP, both eat timers, both attack cooldowns, weapon held, food counts), both sides choosing optimally, whose output is a win probability per matchup. The value of a switch is then "win probability with it minus without it", with no weights and no percentiles. HP ≤ 99, eat timers ≤ 3, cooldowns ≤ 7 and two weapons each give low millions of states per pair, so value iteration in Rust should take seconds per matchup, which is fine for the 32-opponent panel and the top few thousand kits, not for every kit. The first version should be distance-1 with no PID, because verified timing data for distance and player ordering does not exist yet (see [`research/experiments`](../research/experiments)). Open modelling choices: whether running away is a terminal action with a payoff so kill pressure has value when nobody dies; whether the range-to-melee stack lands in the same tick or one tick apart with a chance to react; and whether the equilibrium must be solved or a fixed threshold-eating policy is close enough for ranking. Progress is tracked in [status.md](status.md).
