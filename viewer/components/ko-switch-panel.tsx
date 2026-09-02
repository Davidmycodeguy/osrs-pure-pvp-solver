'use client';

import { Swords } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import {
  type FieldIndex,
  type KitDataset,
  type RawRow,
  numberAt,
  percentAt,
  stringAt,
  tierClasses,
} from '@/lib/dataset';

type Props = {
  kits: KitDataset;
  kitIndex: FieldIndex;
  kit: RawRow;
  build: RawRow;
  buildIndex: FieldIndex;
  /** Kit row indices for every kit that extends this build, in kit-rank order. */
  options: number[];
  selectedKit: number;
  onSelectKit: (kitIndex: number) => void;
};

function Tile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 p-3">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 font-mono text-sm font-semibold">{value}</p>
      {hint ? (
        <p className="mt-1 text-[10px] text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}

function Bar({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono font-medium">{value.toFixed(2)}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary"
          style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
        />
      </div>
    </div>
  );
}

export function KoSwitchPanel({
  kits,
  kitIndex,
  kit,
  build,
  buildIndex,
  options,
  selectedKit,
  onSelectKit,
}: Props) {
  const scale = kits.scale;
  const baseline = numberAt(kit, kitIndex, 'baseline') === 1;
  const neck = stringAt(kit, kits.strings, kitIndex, 'ko_neck');
  const koWeapon = baseline
    ? 'No switch (single weapon)'
    : `${stringAt(kit, kits.strings, kitIndex, 'ko_weapon')}${neck ? ` + ${neck}` : ''}`;
  const windows = [
    ['4 ticks', 'ko_4', 'switch_ko_4'],
    ['5 ticks', 'ko_5', 'switch_ko_5'],
    ['8 ticks', 'ko_8', 'switch_ko_8'],
    ['12 ticks', 'ko_12', 'switch_ko_12'],
  ] as const;
  return (
    <>
      <section className="rounded-lg border border-primary/20 bg-primary/6 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs font-medium text-primary">
              <Swords className="size-4" /> KO switch kit
            </div>
            <p className="mt-1 truncate text-base font-semibold">{koWeapon}</p>
          </div>
          <div className="text-right">
            <Badge
              variant="outline"
              className={tierClasses(
                stringAt(kit, kits.strings, kitIndex, 'tier'),
              )}
            >
              Kit tier {stringAt(kit, kits.strings, kitIndex, 'tier')}
            </Badge>
            <p className="mt-1 font-mono text-xs text-muted-foreground">
              Kit rank #{numberAt(kit, kitIndex, 'rank').toLocaleString()}
            </p>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-2">
          <Tile
            label="KO max hit"
            value={numberAt(kit, kitIndex, 'ko_max_hit')}
            hint={`vs ${numberAt(build, buildIndex, 'max_hit')} primary`}
          />
          <Tile
            label="KO attack roll"
            value={numberAt(kit, kitIndex, 'ko_attack_roll').toLocaleString()}
          />
          <Tile
            label="KO speed"
            value={`${numberAt(kit, kitIndex, 'ko_cooldown')} ticks`}
          />
          <Tile
            label="Switch slots"
            value={numberAt(kit, kitIndex, 'switch_slots')}
          />
          <Tile
            label="Food slots"
            value={numberAt(kit, kitIndex, 'food_slots')}
          />
          <Tile
            label="Race margin"
            value={`${(numberAt(kit, kitIndex, 'race_p3_mean_fish') / 100).toFixed(1)} fish`}
            hint="mean vs panel, 3-tick eats"
          />
        </div>
        <p className="section-label mt-4">
          Kill pressure (raw odds, not percentiles)
        </p>
        <div className="mt-2 grid grid-cols-3 gap-2">
          <Tile
            label="Beats one fish"
            value={`${percentAt(kit, kitIndex, 'pressure', scale).toFixed(1)}%`}
            hint="burst > 14 HP"
          />
          <Tile
            label="Bite over heal"
            value={`+${(numberAt(kit, kitIndex, 'bite') / 100).toFixed(2)} HP`}
            hint="expected overshoot"
          />
          <Tile
            label="Pressure rank"
            value={`#${numberAt(kit, kitIndex, 'pressure_rank').toLocaleString()}`}
            hint="pressure, bite, race"
          />
        </div>
        <div className="mt-2 grid grid-cols-3 gap-2">
          <Tile
            label="Max combo"
            value={`${numberAt(kit, kitIndex, 'max_burst')} HP`}
            hint="biggest unanswerable burst"
          />
          <Tile
            label="Strength potions"
            value={numberAt(kit, kitIndex, 'potions')}
            hint="1 slot each; melee hits use potted max"
          />
          <Tile
            label="vs one fish"
            value="14 HP"
            hint="the heal a burst must beat"
          />
        </div>
        {stringAt(kit, kits.strings, kitIndex, 'spell') ? (
          <div className="mt-2 grid grid-cols-3 gap-2">
            <Tile
              label="Carried spell"
              value={stringAt(kit, kits.strings, kitIndex, 'spell')}
              hint="cast bare-handed, 5 ticks"
            />
            <Tile
              label="Spell max hit"
              value={numberAt(kit, kitIndex, 'spell_max_hit')}
            />
            <Tile
              label="Rune slots"
              value={numberAt(kit, kitIndex, 'rune_slots')}
              hint="one per rune type"
            />
          </div>
        ) : null}
        <div className="mt-2 grid grid-cols-3 gap-2">
          {[
            ['Finish at 10 HP', 'finish_10'],
            ['Finish at 15 HP', 'finish_15'],
            ['Finish at 20 HP', 'finish_20'],
          ].map(([label, field]) => (
            <Tile
              key={field}
              label={label}
              value={`${percentAt(kit, kitIndex, field, scale).toFixed(1)}%`}
            />
          ))}
        </div>
        <p className="section-label mt-4">
          Arrow + KO hit stack (rapid shortbow only)
        </p>
        <div className="mt-2 grid grid-cols-3 gap-2">
          {[
            ['≥15 HP', 'stack_15'],
            ['≥20 HP', 'stack_20'],
            ['≥30 HP', 'stack_30'],
          ].map(([label, field]) => (
            <Tile
              key={field}
              label={label}
              value={`${percentAt(kit, kitIndex, field, scale).toFixed(1)}%`}
            />
          ))}
        </div>
        <p className="section-label mt-4">Cadence KO by window</p>
        <table className="mt-2 w-full text-xs">
          <thead className="text-[10px] uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="py-1 text-left">Window</th>
              <th className="py-1 text-right">No switch</th>
              <th className="py-1 text-right">With switch</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {windows.map(([label, base, switched]) => {
              const before = percentAt(build, buildIndex, base);
              const after = percentAt(kit, kitIndex, switched, scale);
              return (
                <tr key={label} className="border-t border-border/60">
                  <td className="py-1.5">{label}</td>
                  <td className="py-1.5 text-right text-muted-foreground">
                    {before.toFixed(1)}%
                  </td>
                  <td
                    className={`py-1.5 text-right ${after > before + 0.05 ? 'text-emerald-300' : ''}`}
                  >
                    {after.toFixed(1)}%
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="mt-4 space-y-3">
          <Bar
            label="Kit race"
            value={percentAt(kit, kitIndex, 'race_score', scale)}
          />
          <Bar
            label="KO switch"
            value={percentAt(kit, kitIndex, 'ko_switch_score', scale)}
          />
        </div>
      </section>

      <section>
        <p className="section-label">
          All KO options for this build ({options.length})
        </p>
        <div className="mt-2 max-h-72 overflow-y-auto rounded-lg border border-border">
          <table className="w-full text-xs">
            <tbody>
              {options.map((kitRow) => {
                const option = kits.rows[kitRow];
                const optionBaseline =
                  numberAt(option, kitIndex, 'baseline') === 1;
                return (
                  <tr
                    key={kitRow}
                    className={`cursor-pointer border-b border-border/60 hover:bg-primary/6 ${kitRow === selectedKit ? 'bg-primary/10' : ''}`}
                    onClick={() => onSelectKit(kitRow)}
                  >
                    <td className="px-2 py-1.5 font-mono text-muted-foreground">
                      #{numberAt(option, kitIndex, 'rank').toLocaleString()}
                    </td>
                    <td className="px-2 py-1.5">
                      {optionBaseline
                        ? 'No switch'
                        : stringAt(option, kits.strings, kitIndex, 'ko_weapon')}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono">
                      {numberAt(option, kitIndex, 'ko_max_hit')} max
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono">
                      {numberAt(option, kitIndex, 'food_slots')} food
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono text-primary">
                      {percentAt(option, kitIndex, 'score', scale).toFixed(2)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
