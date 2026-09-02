'use client';

import { useMemo, useState } from 'react';
import { Search } from 'lucide-react';

import { Input } from '@/components/ui/input';

type Term = { name: string; where: string; meaning: string; caveat?: string };

const TERMS: Term[] = [
  {
    name: 'Kit rank',
    where: 'KO kits table, panel header',
    meaning:
      'Position under the attrition ranking: the mean of six category percentiles (sustain, race, burst, defence, utility, KO switch). Lower is better.',
    caveat:
      'Rewards winning a long eat-perfectly trade. A build that can never finish a fight can still rank near the top.',
  },
  {
    name: 'Pressure rank (P#)',
    where: 'Kill pressure column, panel tile',
    meaning:
      'Position under the kill-pressure ranking: sorted by "beats one fish", then bite, then race margin. Lower is better.',
    caveat:
      'Ignores accuracy of the chip weapon beyond the race tiebreak. Diagnostic, not a fight simulation.',
  },
  {
    name: 'Kill pressure / Beats one fish',
    where: 'Kill pressure column, panel tile',
    meaning:
      'Exact probability that the best unanswerable burst does more than 14 damage, which is what one swordfish heals. For rapid shortbow kits the burst is one arrow plus one KO hit landing together; for other kits it is the single hardest hit. Averaged over three opponent defence levels.',
    caveat:
      'Uses 14 for fish. A pizza half heals 9, so pressure against pizza eaters is higher than shown.',
  },
  {
    name: 'Max combo',
    where: 'KO kits table (KO switch cell), panel tile',
    meaning:
      'The biggest single unanswerable burst this kit can land: arrow + KO hit for stack kits, else the hardest single hit. Potion included when carried.',
  },
  {
    name: 'Strength potions',
    where: 'Panel tile, run setting',
    meaning:
      'Potions carried (default 1). Each costs one inventory slot; melee hits in the stack, switch and kill-pressure tables use the potted max hit (boost 3 + Strength÷10). Drinking adds no attack delay. The race still uses unpotted damage.',
    caveat: 'Only Strength potions; no Ranged or Magic potions exist in F2P.',
  },
  {
    name: 'KO amulet / amulet switch',
    where: 'KO weapon text, column picker',
    meaning:
      'The KO loadout may swap the worn amulet for the Amulet of strength (+10 melee strength vs +6 on power) when that raises the KO max hit. Costs one more inventory slot; shown as "weapon + Amulet of strength".',
  },
  {
    name: 'Spell (runes) / Rune slots',
    where: 'KO kits table, panel tiles',
    meaning:
      'A second variant of each kit carries the hardest F2P spell the account can cast when it out-hits the primary weapon (Fire Bolt at 35 Magic hits 12; Wind Blast at 41 hits 13). Cast without a staff, so each rune type costs one inventory slot. The spell counts in the race, as an opener in the switch windows, and as a single-hit burst for kill pressure.',
    caveat:
      'Opponent magic defence uses the standard 70% Magic / 30% Defence rule, which is not a verified ruleset mechanic. No magic-to-melee stack is modelled.',
  },
  {
    name: 'Bite over heal',
    where: 'Panel tile',
    meaning:
      'Expected damage beyond 14 when the burst beats it, in HP. Separates "barely beats a fish" from "opens a real kill window".',
  },
  {
    name: 'Finish at 10 / 15 / 20 HP',
    where: 'Panel tiles',
    meaning:
      'Probability the burst does at least that much damage: the chance to kill an opponent sitting at that HP who cannot eat in time.',
  },
  {
    name: 'Stack ≥15 / ≥20 / ≥30',
    where: 'KO kits table, panel',
    meaning:
      'Probability one rapid arrow plus one KO hit totals at least that much. Only rapid shortbow primaries can stack; everything else shows 0.',
  },
  {
    name: 'Kit score',
    where: 'Panel header, table Score column',
    meaning:
      'Mean of six category percentiles over all kits at this combat level, shown as a percentage. 89.03 means the kit averages the 89th percentile across categories.',
    caveat: 'Percentile of position, not a win probability.',
  },
  {
    name: 'Build score',
    where: 'Panel header (small), build tables',
    meaning:
      'Same idea over five categories and the single-weapon build population. This is the older Stage 4 number and knows nothing about switching.',
  },
  {
    name: 'Sustain',
    where: 'Build ranking dimensions',
    meaning:
      'Damage per tick against low, medium and high defence rolls: hit chance × average damage ÷ attack speed.',
  },
  {
    name: 'Notional race / Kit race',
    where: 'Ranking bars, Race margin tile',
    meaning:
      'Closed-form attrition: each side loses attack time to eating (3 ticks per fish), time-to-kill is (HP + food×14) ÷ effective damage per tick, and the margin is how many fish the winner has to spare against each of 32 panel opponents. Kits carry 28 minus switch-slot food.',
    caveat:
      'Assumes both players eat perfectly on time and every eat fully heals. This is the source of the attrition bias.',
  },
  {
    name: 'Burst / KO',
    where: 'Ranking bars, 4t/5t/8t/12t KO tiles',
    meaning:
      'Probability that repeated hits of one weapon inside a 4, 5, 8 or 12-tick window reach 5 to 30 HP, averaged; plus max hit and potted max hit.',
  },
  {
    name: 'With switch (cadence table)',
    where: 'Panel window table',
    meaning:
      'Same windows, but the KO weapon fires as soon as the carried-over cooldown expires. Equal to "no switch" when repeated arrows out-damage arrow plus KO inside the window.',
  },
  {
    name: 'Defence (category)',
    where: 'Ranking bars, defence rolls',
    meaning:
      "Stab, slash, crush and ranged defence rolls of the worn gear at the account's Defence level, plus magic defence bonus.",
  },
  {
    name: 'Def (Defence level)',
    where: 'Levels pills, Columns picker',
    meaning:
      "The account's Defence level, 1 to 40. Every 4 Defence costs one combat level (same rate as Hitpoints) and Defence training adds Hitpoints XP like Attack does. Defence 1 accounts are the original pures; higher levels unlock iron through rune armour, studded and green dragonhide bodies, and kiteshields.",
    caveat:
      'Armour pruning keeps the offence-best items plus one full tank loadout per weapon, not every mixed combination.',
  },
  {
    name: 'Utility',
    where: 'Ranking bars',
    meaning:
      'Attack range, number of attack styles, Prayer level and bonus, magic attack bonus.',
    caveat:
      'Carries the same weight as KO in the kit score; most of it does nothing in a real fight.',
  },
  {
    name: 'Food slots / Switch slots',
    where: 'KO kits table, panel tiles',
    meaning:
      'A carried switch costs one inventory slot per item not shared between loadouts (a 2H replacing a weapon and shield costs 2). Food is 28 minus that.',
  },
  {
    name: 'KO max hit / attack roll / speed',
    where: 'Panel tiles',
    meaning:
      'The switch weapon on this account: highest max hit across its styles, best attack roll, and cooldown in ticks (0.6 s each).',
  },
  {
    name: 'Tier',
    where: 'Badges',
    meaning:
      'S = top 1%, A = next to 5%, B = next to 20%, N = lower but a panel seed or niche extreme, C = remainder. Applies to whichever ranking the badge sits next to.',
  },
  {
    name: 'Simulator 32',
    where: 'Filter button',
    meaning:
      'The 32 opponent builds used as the race panel: chosen to be diverse (each damage type, each weapon type, farthest-point sampling on the metrics).',
  },
  {
    name: 'No-switch KO 4/5/8/12t %',
    where: 'Column picker',
    meaning:
      'The primary weapon alone, repeated on its own cooldown inside the window, chance to reach the averaged HP thresholds. Same numbers as the 4t/5t/8t/12t KO tiles.',
  },
  {
    name: 'DPT low / med / high',
    where: 'Column picker',
    meaning:
      'Sustained damage per tick of the primary weapon against a low, medium or high defence roll (population 10th, 50th, 90th percentile).',
  },
  {
    name: 'Primary attack roll / max hit',
    where: 'Column picker',
    meaning:
      "The single-weapon build's best attack roll and max hit before any switch or potion.",
  },
  {
    name: 'Race mean fish',
    where: 'Column picker, panel tile',
    meaning:
      'Mean race margin across the 32-opponent panel with 3-tick eats, in fish. Positive means the kit out-lasts the panel on average.',
  },
  {
    name: 'Copy rows as CSV',
    where: 'Below the KO kits table',
    meaning:
      'Copies the currently filtered and sorted kits with the visible columns to the clipboard, at most 50,000 rows. For everything, use the full files: outputs/cb30-rust/kits-cb30.csv (1.6 GB) and outputs/cb40-rust/kits-cb40.csv (3 GB). Open them with DuckDB or pandas, not Excel.',
  },
  {
    name: 'Unique envelopes',
    where: 'View toggle',
    meaning:
      'Builds grouped by identical combat numbers so accounts that differ only in unused levels collapse into one row.',
  },
];

export function Glossary() {
  const [query, setQuery] = useState('');
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return TERMS;
    return TERMS.filter((term) =>
      `${term.name} ${term.where} ${term.meaning} ${term.caveat ?? ''}`
        .toLowerCase()
        .includes(needle),
    );
  }, [query]);
  return (
    <section className="panel mb-4 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="font-semibold">What the numbers mean</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Every column and tile, where it appears, how it is computed, and
            what it cannot tell you.
          </p>
        </div>
        <div className="relative sm:w-72">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Search glossary"
            className="h-9 pl-9"
            placeholder="Search a term…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-2">
        {visible.map((term) => (
          <div
            key={term.name}
            className="rounded-lg border border-border bg-muted/25 p-3 text-xs"
          >
            <div className="flex items-baseline justify-between gap-2">
              <p className="font-semibold">{term.name}</p>
              <p className="shrink-0 text-[10px] uppercase tracking-wide text-muted-foreground">
                {term.where}
              </p>
            </div>
            <p className="mt-1 text-muted-foreground">{term.meaning}</p>
            {term.caveat ? (
              <p className="mt-1 text-amber-200/80">Caveat: {term.caveat}</p>
            ) : null}
          </div>
        ))}
        {visible.length === 0 ? (
          <p className="text-xs text-muted-foreground">No term matches.</p>
        ) : null}
      </div>
    </section>
  );
}
