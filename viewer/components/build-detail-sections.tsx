'use client';

import { Sparkles } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { MetricBar, StatTile } from '@/components/metric-tiles';
import {
  type Dataset,
  type FieldIndex,
  type RawRow,
  decimalAt,
  gearFields,
  numberAt,
  percentAt,
  stringAt,
} from '@/lib/dataset';
import { prettyReason } from '@/lib/filtering';

type BuildProps = { selected: RawRow; index: FieldIndex };
type NamedBuildProps = BuildProps & { data: Dataset };

const levelCells = [
  ['A', 'attack'],
  ['S', 'strength'],
  ['R', 'ranged'],
  ['M', 'magic'],
  ['P', 'prayer_level'],
  ['D', 'defence_level'],
  ['HP', 'hitpoints'],
];
const dptTiles = [
  ['Low def DPT', 'dpt_low'],
  ['Med def DPT', 'dpt_medium'],
  ['High def DPT', 'dpt_high'],
];
const koTiles = [
  ['4t KO', 'ko_4'],
  ['5t KO', 'ko_5'],
  ['8t KO', 'ko_8'],
  ['12t KO', 'ko_12'],
];
const bonusStyles = ['stab', 'slash', 'crush', 'magic', 'ranged'];
const rankingBars = [
  ['Sustain', 'sustain_score'],
  ['Notional race', 'race_score'],
  ['Burst / KO', 'burst_score'],
  ['Defence', 'defence_score'],
  ['Utility', 'utility_score'],
];

export function AccountLevels({ selected, index }: BuildProps) {
  return (
    <section>
      <p className="section-label">Account levels</p>
      <div className="mt-3 grid grid-cols-7 gap-1.5">
        {levelCells.map(([label, field]) => (
          <div
            key={field}
            className="rounded-lg border border-border bg-muted/35 px-1 py-2 text-center"
          >
            <p className="text-[9px] font-semibold text-muted-foreground">
              {label}
            </p>
            <p className="mt-0.5 font-mono text-sm font-semibold">
              {numberAt(selected, index, field)}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

export function ModelledGear({ selected, data, index }: NamedBuildProps) {
  return (
    <section>
      <p className="section-label">Full modelled gear</p>
      <div className="mt-3 grid grid-cols-2 gap-2">
        {gearFields.map((field) => {
          const item =
            stringAt(selected, data.strings, index, field) || 'Empty';
          const itemId = numberAt(selected, index, `${field}_id`);
          return (
            <div key={field} className="gear-slot">
              <span className="grid size-8 shrink-0 place-items-center rounded-md bg-primary/10 font-mono text-[10px] font-bold uppercase text-primary">
                {field.slice(0, 2)}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-xs font-medium">
                  {item}
                </span>
                <span className="block font-mono text-[9px] text-muted-foreground">
                  {itemId >= 0 ? `ID ${itemId}` : 'No item'}
                </span>
              </span>
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-[10px] text-muted-foreground">
        Cape, feet and ring are absent because the source matrix did not
        enumerate those slots.
      </p>
    </section>
  );
}

export function CombatOutput({ selected, index }: BuildProps) {
  return (
    <section>
      <p className="section-label">Combat output</p>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4 2xl:grid-cols-2">
        <StatTile
          label="Attack roll"
          value={numberAt(
            selected,
            index,
            'maximum_attack_roll',
          ).toLocaleString()}
        />
        <StatTile
          label="Max hit"
          value={numberAt(selected, index, 'max_hit')}
          hint={`Potted ${numberAt(selected, index, 'potted_max_hit')}`}
        />
        <StatTile
          label="Attack speed"
          value={`${numberAt(selected, index, 'weapon_speed')} ticks`}
        />
        <StatTile
          label="Range"
          value={`${numberAt(selected, index, 'maximum_range')} tiles`}
          hint={`Base ${numberAt(selected, index, 'weapon_base_range')}`}
        />
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2">
        {dptTiles.map(([label, field]) => (
          <StatTile
            key={field}
            label={label}
            value={decimalAt(selected, index, field).toFixed(3)}
          />
        ))}
      </div>
      <div className="mt-2 grid grid-cols-4 gap-2">
        {koTiles.map(([label, field]) => (
          <StatTile
            key={field}
            label={label}
            value={`${percentAt(selected, index, field).toFixed(1)}%`}
          />
        ))}
      </div>
    </section>
  );
}

export function BonusGrids({ selected, index }: BuildProps) {
  return (
    <section className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-1">
      <div>
        <p className="section-label">Attack bonuses</p>
        <div className="mt-3 stat-grid">
          {bonusStyles.map((style) => (
            <div key={style}>
              <span>{style}</span>
              <b>{numberAt(selected, index, `attack_${style}`)}</b>
            </div>
          ))}
          <div>
            <span>Melee str</span>
            <b>{numberAt(selected, index, 'melee_strength')}</b>
          </div>
          <div>
            <span>Ranged str</span>
            <b>{numberAt(selected, index, 'ranged_strength')}</b>
          </div>
          <div>
            <span>Prayer</span>
            <b>{numberAt(selected, index, 'prayer_bonus')}</b>
          </div>
        </div>
      </div>
      <div>
        <p className="section-label">Defence bonuses</p>
        <div className="mt-3 stat-grid">
          {bonusStyles.map((style) => (
            <div key={style}>
              <span>{style}</span>
              <b>{numberAt(selected, index, `defence_${style}`)}</b>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function RankingDimensions({ selected, index }: BuildProps) {
  return (
    <section>
      <p className="section-label">Build ranking dimensions</p>
      <div className="mt-3 space-y-3">
        {rankingBars.map(([label, field]) => (
          <MetricBar
            key={field}
            label={label}
            value={percentAt(selected, index, field)}
          />
        ))}
      </div>
    </section>
  );
}

export function RankReasons({ selected, data, index }: NamedBuildProps) {
  return (
    <section>
      <p className="section-label">Why it ranks here</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {stringAt(selected, data.strings, index, 'rank_reasons')
          .split(';')
          .filter(Boolean)
          .map((reason) => (
            <Badge
              key={reason}
              variant="outline"
              className="border-emerald-400/20 bg-emerald-400/8 text-emerald-300"
            >
              {prettyReason(reason)}
            </Badge>
          ))}
      </div>
    </section>
  );
}

export function AuditDetails({ selected, data, index }: NamedBuildProps) {
  return (
    <section className="rounded-lg border border-border bg-muted/25 p-3">
      <div className="flex items-center gap-2 text-xs font-medium">
        <Sparkles className="size-4 text-primary" /> Audit details
      </div>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
        <dt>Candidate</dt>
        <dd className="truncate font-mono text-foreground">
          {stringAt(selected, data.strings, index, 'candidate_id')}
        </dd>
        <dt>Profile</dt>
        <dd className="font-mono text-foreground">
          {numberAt(selected, index, 'profile_id')}
        </dd>
        <dt>Weapon styles</dt>
        <dd className="text-foreground">
          {stringAt(selected, data.strings, index, 'weapon_styles').replaceAll(
            '_',
            ' ',
          )}
        </dd>
        <dt>Required</dt>
        <dd className="text-foreground">
          A {numberAt(selected, index, 'req_attack')} · S{' '}
          {numberAt(selected, index, 'req_strength')} · R{' '}
          {numberAt(selected, index, 'req_ranged')}
        </dd>
      </dl>
    </section>
  );
}
