# OSRS F2P Pure PvP Build Solver

[![CI](https://github.com/Davidmycodeguy/osrs-pure-pvp-solver/actions/workflows/ci.yml/badge.svg)](https://github.com/Davidmycodeguy/osrs-pure-pvp-solver/actions/workflows/ci.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
![Rust](https://img.shields.io/badge/rust-2021-orange)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)

**What is the mathematically best free-to-play pure build for PvP in Old School RuneScape at combat level 30 or 40? This computes the answer with exact combat math, and is built to grow into a reinforcement-learning agent that proves it in real fights.**

Every guide just repeats whichever build is popular. This does the math instead: it takes every item, every skill-level split, every attack style and every inventory a pure at that combat level can legally use, runs each one through the same fight math the game uses against a panel of opponents, and ranks the lot. The output is a ranked list of builds, a ranked list of knockout kits, and a browser app (PureLab) for digging through them.

The project runs in two phases:

1. **Exact math, built now.** Closed-form probability arithmetic, not dice rolls, ranks every legal build and knockout kit. Every hit is a full damage distribution, combos are convolved exactly, and every rerun is byte-identical. This is what the repository does today.
2. **Reinforcement-learning validation, the goal.** The math assumes both players play perfectly, which real fights are not. The headline roadmap item is to play the top builds against each other on a private OSRS server and train a reinforcement-learning agent on each side, starting from [osrs-pvp-reinforcement-learning](https://github.com/Naton1/osrs-pvp-reinforcement-learning), to measure which builds actually win and where the closed-form model is wrong.

The short answer today, for fights against real people: a low-Attack, high-Strength shortbow pure carrying a Rune warhammer switch and a Strength potion. The rest of this page is why, and what the model still gets wrong.

![PureLab viewer: ranked knockout kits at combat level 40](docs/screenshots/kits-view.png)

## How it works

Seven steps, in order. Each one is a stage or a tool in this repo.

### 1. Stat validator

Every number the solver uses comes from a pinned OSRS Wiki revision, and every item and mechanic has to pass a recorded review decision before the math is allowed to read it. If a fact is missing, unverified or contradicted by another source, the run stops with an error instead of guessing.

Why: so the results reflect the live game rather than what I remember about it, and so the whole ruleset can be re-audited or refreshed when the game changes. The committed data is proven regenerable from the archived wiki pages on every test run. [docs/data-provenance.md](docs/data-provenance.md) describes the verification model.

### 2. Gather every stat

The verified ruleset in [`rulesets/osrs-f2p-v1`](rulesets/osrs-f2p-v1) holds 150 F2P equipment records (bonuses, requirements, attack styles, ammo, two-handedness), 7 foods and the Strength potion as state graphs, the F2P spellbook and prayers, and 53 game mechanics written as formula trees (combat level, hit chance, max hit, attack speed, experience). Every record cites the wiki revisions it came from.

### 3. Every level combination

For the chosen combat level, the solver enumerates every Attack, Strength, Defence, Ranged, Magic, Prayer and Hitpoints split that lands on exactly that level, with Hitpoints tied to what training those skills would actually give. That is millions of raw states per level, reduced to a few thousand accounts that are not strictly worse than another. (Pipeline stage 1.)

### 4. Every gear and attack-style combination

Each account is given every weapon it can wield, the best armour for that weapon, the best ammunition, and every attack style. The combat kernel resolves each one into exact attack rolls, max hits, cooldowns and defence rolls, then drops any candidate that is strictly worse than another on the same account. (Stages 2 and 3.)

### 5. Inventory heuristic

You have 28 slots, and every slot that is not food is a heal you do not get. For each surviving build the solver tries a small set of inventory options and keeps the ones that raise the knockout hit:

- **No switch.** All 28 slots are food. The baseline.
- **A carried knockout weapon** that out-hits the primary, for example a Rune warhammer behind a Maple shortbow, costing one or two slots.
- **An Amulet of strength swap** alongside the knockout weapon, costing one more slot.
- **A Strength potion** in one slot, so the melee hit uses the boosted max hit.
- **Runes for the hardest spell** the account can cast, when its max hit beats the weapon, costing one slot per rune type.

Food is whatever is left: 28 minus switch slots, potions and rune slots. Options are kept only when they raise the knockout max hit, and a build that gains nothing from switching stays as its baseline. (Stage 5.)

### 6. Fight simulator

Every kit fights a panel of 32 opponents chosen to cover the population: the extremes on each metric, one representative per weapon and damage type, then farthest-point sampling over the rest. The fight math is exact probability arithmetic rather than dice rolls. Each hit is a full damage distribution, and combos are convolved, so "chance that a rapid arrow plus a warhammer hit does at least 15" is an exact number that counts every lucky roll.

Per kit and opponent it computes sustained damage per tick, knockout odds in 4, 5, 8 and 12-tick windows, the arrow-plus-switch stack, an attrition food race where every eat costs an attack, and kill pressure: the chance that the best unanswerable combo does more than one fish heals. (Stages 4 and 5.) [docs/methodology.md](docs/methodology.md) has the formulas.

### 7. Rankings

Two rankings come out, on purpose. The **attrition ranking** rewards winning a long, eat-perfectly trade. The **kill-pressure ranking** rewards being able to end the fight. They disagree by a lot, and the viewer shows both. Everything is computed in exact rational arithmetic, so a rerun gives byte-identical files.

## What the model accounts for

So you can judge how realistic a ranking is, this is everything the fight math includes, next to what it leaves out. Every included mechanic is a pinned wiki formula in [`mechanics.json`](rulesets/osrs-f2p-v1/mechanics.json); [docs/methodology.md](docs/methodology.md) has each formula written out.

| Area | Included | Not included |
| --- | --- | --- |
| **Levels** | All seven combat skills. The exact combat-level formula. Hitpoints tied to the XP the other skills would give. Prayer on verified breakpoints. Defence at 1, or any list of levels. | Quest or non-combat Hitpoints XP. |
| **Gear** | 150 verified F2P items across head, neck, body, legs, hands, weapon, shield and ammo. Bronze to rune melee (sword, scimitar, mace, warhammer, battleaxe, 2h), shortbows and longbows to maple, the willow comp bow, crossbows, the four elemental staves, Hill giant club, Ham joint, Goblin paint cannon, all four amulets, leather to green d'hide, sq shields and kiteshields, Anti-dragon shield, Mooleta, arrows bronze to adamant. | Cape, boots and ring slots. Shield is only Mooleta on the offensive path, plus the single most defensive legal shield. |
| **Item stats** | All 14 bonuses per item: attack and defence for stab, slash, crush, ranged and magic, melee strength, ranged strength, magic damage and prayer. Attack speed in ticks, attack range, two-handedness, ammo compatibility, skill and quest requirements (Dragon Slayer I gates rune platebody, green d'hide body and the Anti-dragon shield), F2P-only and obtainable. | Item weight, degrade, special attacks (F2P has none). |
| **Gear resistance** | Your armour's stab, slash, crush and ranged defence are summed and rolled against the attacker's damage type: a scimitar's slash hits your slash defence, a warhammer's crush hits your crush defence, arrows hit your ranged defence. Defence roll is effective Defence × (bonus + 64) with the pinned accuracy formula, and it runs both ways against every opponent on the panel. Magic defence uses your magic defence bonus. | Defence boosts and prayer on the defence roll. The opponent's magic defence uses the standard 70 % Magic / 30 % Defence rule, which is flagged unverified. Shield defence loss when you switch to a 2h weapon. |
| **Attack styles** | Every verified style per weapon: accurate +3 Attack, aggressive +3 Strength, controlled +1 each, defensive +3 Defence, longrange +3 Defence and +2 range, rapid one tick faster on bows. Each metric takes the best style. | Style switching mid-fight. |
| **Hit math** | Effective levels, attack rolls, the OSRS hit-chance formula, uniform damage from 0 to max hit with a successful 0 becoming 1 in PvP, the wiki max-hit formulas for melee, ranged and magic. Every hit is kept as a full probability distribution and combos are convolved, so stack odds are exact. | Nothing approximated here. |
| **Speed and switching** | Per-weapon attack speed (scimitar 4, warhammer 6, 2h 7, maple shortbow on rapid 3). Switching costs zero ticks, the remaining cooldown carries over, and the new weapon's speed applies after it fires. | Movement and distance, projectile flight ticks, PID order, the drink delay on potions. |
| **Prayer** | The strongest offensive prayer the account's Prayer level unlocks is active as a fixed multiplier. Gear prayer bonus counts in the utility score. | Prayer drain, flicking, protection prayers and prayer switching. The verified drain and protection mechanics exist in the ruleset but are not used by the rankings yet. |
| **Potions** | One Strength potion, boost 3 + floor(Strength ÷ 10), applied to melee hits in the knockout and kill-pressure tables. | Ranged or magic potions (not in F2P). Potion timing and re-dosing. The race stays unpotted. |
| **Food** | Seven verified foods as state graphs (swordfish, lobster, tuna, anchovy pizza, meat pizza, pumpkin, easter egg). The rankings race on swordfish: heals 14, 3-tick eat delay, every eat is a lost attack. | Mixed inventories, pizza's two-bite timing in the race, combo eating. |
| **Magic** | The F2P spellbook (Fire Bolt 12 at 35 Magic, Wind Blast 13 at 41, Fire Blast 16 at 59, and the rest), 5-tick cast, rune cost, gear magic attack bonus, the best F2P magic prayer. | Staff-held casting (spells are costed bare-handed, so a bolt costs three rune slots). Magic-to-melee stacks. |
| **Inventory** | 28 slots. A carried switch costs one slot per item not shared between loadouts, ammo is free, a 2h switch on a shield user costs two, an amulet swap one, a potion one, each rune type one. Food is the remainder. | More than one switch weapon. More than one potion. |
| **Opponents** | 32 opponents chosen to span the population, each with full food, fought both ways with their own armour and damage type against yours. | Opponents who switch, cast, pray or change policy. Any opponent outside F2P at that combat level. |
| **Death** | A fight ends when HP reaches 0. The knockout tables count damage past one fish heal. | Running away. Simultaneous knockouts. Who acts first on the tick. |

Every report file also carries a `verification` block that restates these limits in machine-readable form, so a number is never separated from what it does not model.

## What it found

For 1v1 F2P fights with a full inventory of swordfish, as of 2026-09-02:

| Combat level | Best kit by kill pressure | Beats one fish | Max combo |
| --- | --- | --- | --- |
| 30 | 7 Attack / 52 Strength / 39 Ranged, 44 Hitpoints. Maple shortbow on rapid into a Rune warhammer with an Amulet of strength switch, Strength potion carried | 20.8 % | 23 |
| 40 | 21 Attack / 55 Strength / 51 Ranged, 49 Hitpoints. Same kit | 37.9 % | 28 |

Two findings held up in every run:

- **Warhammers need Strength, not Attack.** A near-zero-Attack, Strength-dumped account gets a big knockout weapon without spending combat level on Attack. The search found this on its own.
- **A build that cannot finish a fight still wins the attrition model.** The best single-weapon build has nothing to switch to and drops from rank 1 to rank 913 once switches exist. That gap is the open modelling problem and the reason there are two rankings.

These are priority rankings from a closed-form model, not measured win rates. [docs/results.md](docs/results.md) has every table with dates, including what happens when Defence is opened up.

## Which build should you play?

It depends on who you are fighting.

**Against a bot that plays perfectly**, the fight is a war of attrition. If both sides eat exactly on time and never misclick, nobody ever gets knocked out, and the winner is whoever lands more chip damage over a long trade. That is what the attrition ranking measures, and it favours Attack for accuracy and Ranged for chip. In that world a knockout weapon is a rounding error.

**Against real humans, play the kill-pressure build.** People eat late, misclick, get caught eat-locked, and run when a fight turns. A kit whose arrow-plus-warhammer combo beats one fish heal about 38 % of the time at level 40 does three things the attrition build cannot:

- It forces the opponent to eat early, at a higher HP, because a max combo is always live. Every early eat is attacks they do not get to throw.
- It punishes the slip. After an eat they are locked for 3 ticks, and a combo landing inside that window is unanswerable.
- It ends fights. Without a knockout the losing side just walks away.

The attrition winner has no way to punish anything, so against a human it wins on paper and draws in practice. The pressure-ranked shape, near-zero Attack with Strength dumped so a Rune warhammer hits 14 or more, is also what experienced F2P pures build, which is some evidence the model is pointing the right way. The fight model has no opponent policy yet, so this recommendation is judgement on top of the numbers. Checking it on a real server is the second item on the list below, right behind the play-policy work it builds on.

## See the rankings

The viewer is a browser app that loads the ranked builds and knockout kits for one combat level, lets you filter, sort and pick columns, and explains every number in a glossary. It downloads the datasets from the GitHub release, so it needs Node 22.13+ and Python 3.11+ but not Rust.

```bash
git clone https://github.com/Davidmycodeguy/osrs-pure-pvp-solver.git
cd pure/viewer
npm ci
python scripts/fetch_data.py        # ~56 MB of gzipped datasets from the GitHub release
npm run dev                         # app on http://localhost:3000
```

[docs/viewer.md](docs/viewer.md) is a tour of the screen and the columns.

## Run the search yourself

The math pipeline is a Rust binary run in five stages for one combat level. The classic 1-Defence search at level 40 takes about a minute for stages 1 to 4 and several minutes for stage 5 on a modern desktop, and writes a few GB under `outputs/`.

```bash
cd pure_math && cargo build --release && cd ..

# Linux / macOS
pure_math/scripts/run_pipeline.sh 40 1

# Windows
powershell -File pure_math\scripts\run_pipeline.ps1 -CombatLevel 40 -DefenceLevels '1'

# Export the results for the viewer
python viewer/scripts/export_build_data.py 40
```

To open Defence up, pass a list of levels such as `1,5,10,15,20,30,40` instead of `1`. That run is far larger: the recorded level-40 Defence run sharded stage 3 and shortlisted the survivors before stage 5, and every level from 1 to 40 at once runs out of memory. Every stage, flag and output file is documented in [docs/pipeline.md](docs/pipeline.md), including the [sharding and shortlist steps](docs/pipeline.md#sharding-and-merging).

To work on the data (add an item, fix a mechanic, run the verification tests), install the Python package and read [docs/data-provenance.md](docs/data-provenance.md):

```bash
python -m pip install -e ".[dev]"
python -m pytest tests -q                      # Python verification and reference tests
cd pure_math && cargo test --release           # Rust unit, golden and integration tests
```

## TODO

Roughly in priority order. The first one is in progress.

- [ ] **Optimal play policy** (exploring now). The fight model assumes both players eat perfectly on time and never decide anything else. Replace the closed-form race with a tick-level duel solver that plays out both sides, with eat timers, cooldowns, weapon switches and the choice of when to eat, switch or leave, so a switch is valued by the win probability it adds rather than by a percentile.
- [ ] **Check the winners on a real server.** Take the top kits from both rankings, play them out on a private OSRS server, and train a reinforcement-learning agent on each side of the fight (an environment like [osrs-pvp-reinforcement-learning](https://github.com/Naton1/osrs-pvp-reinforcement-learning) is the starting point). Measured win rates against the ranking will show which parts of the model hold up and which do not.
- [ ] **Movement and distance in the fight simulation.** Every fight is at distance 1 with no projectile flight time and no PID order. Verified timings exist for melee at 1 to 2 tiles, rapid shortbow at 2 tiles and magic at 7 to 8 tiles, and anything else fails closed until the timing experiments are run.
- [ ] **More food and inventory combinations.** Every kit carries swordfish, and the inventory options are the handful of popular setups (knockout weapon, amulet swap, Strength potion, runes) used as a heuristic to keep the search tractable. Mixed food, anchovy pizza, several potions, more than one switch and prayer potions are all unexplored.
- [ ] **Mage pures.** The account search treats Magic as filler, so magic-dominant builds never reach the gear stage. They need their own frontier.
- [ ] **Prayer in fights.** Offensive prayers are a fixed multiplier and protection prayers are not modelled at all.
- [ ] **Catalog gaps.** Shield is not a real slot yet, and cape, boots and ring slots are missing entirely.

[docs/status.md](docs/status.md) has the full roadmap with dates, the known gaps, and what each stage declares it does not model.

## Documentation

| You want to | Read |
| --- | --- |
| Understand what the numbers mean and do not mean | [docs/methodology.md](docs/methodology.md) |
| See every result table | [docs/results.md](docs/results.md) |
| Run or rerun any stage | [docs/getting-started.md](docs/getting-started.md), [docs/pipeline.md](docs/pipeline.md) |
| Know how a mechanic or item gets verified | [docs/data-provenance.md](docs/data-provenance.md) |
| See how the code is put together | [docs/architecture.md](docs/architecture.md) |
| Know what is done, what is missing, and what is next | [docs/status.md](docs/status.md) |
| Contribute | [CONTRIBUTING.md](CONTRIBUTING.md) |

## License and attribution

The code is licensed under the [GNU Affero General Public License v3.0](LICENSE).

The wiki page snapshots in `research/authoritative/` and the data derived from them are © the contributors of the [Old School RuneScape Wiki](https://oldschool.runescape.wiki/) and are used under [CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/). See [research/README.md](research/README.md).

This project is not affiliated with or endorsed by Jagex Ltd. Old School RuneScape is a trademark of Jagex Ltd.
