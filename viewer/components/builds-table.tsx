'use client';

import { ChevronRight } from 'lucide-react';

import { PinButton } from '@/components/pin-button';

import { Badge } from '@/components/ui/badge';
import {
  type Dataset,
  type FieldIndex,
  type KitDataset,
  numberAt,
  percentAt,
  stringAt,
  tierClasses,
} from '@/lib/dataset';
import { canPinMore } from '@/lib/compare';
import { type SortKey, type ViewRow, defenceTotal } from '@/lib/filtering';

const levelPills = [
  ['A', 'attack'],
  ['S', 'strength'],
  ['R', 'ranged'],
  ['D', 'defence_level'],
  ['HP', 'hitpoints'],
];

type Props = {
  data: Dataset;
  index: FieldIndex;
  kits: KitDataset | null;
  kitIndex: FieldIndex;
  /** Kit row indices per build row index, in kit-rank order. */
  kitGroups: Map<number, number[]>;
  /** Build rank -> build row index. */
  rankToIndex: Map<number, number>;
  /** Rows for the current page, already filtered, grouped and sorted. */
  pageRows: ViewRow[];
  selectedRank: number;
  /** Build ranks pinned into the comparison. */
  pinned: readonly number[];
  onSelect: (rank: number) => void;
  onSort: (key: SortKey) => void;
  onTogglePin: (rank: number) => void;
};

function BestKitCell({
  kits,
  kitIndex,
  kitRow,
}: {
  kits: KitDataset | null;
  kitIndex: FieldIndex;
  kitRow: number | undefined;
}) {
  if (!kits || kitRow === undefined)
    return <span className="text-muted-foreground">…</span>;
  const bestKit = kits.rows[kitRow];
  const baseline = numberAt(bestKit, kitIndex, 'baseline') === 1;
  return (
    <>
      <span className="font-semibold text-primary">
        #{numberAt(bestKit, kitIndex, 'rank').toLocaleString()}
      </span>
      <span className="block text-muted-foreground">
        {baseline
          ? 'no switch'
          : stringAt(bestKit, kits.strings, kitIndex, 'ko_weapon')}
      </span>
    </>
  );
}

/** The single-weapon build table shared by the envelopes and profiles views. */
export function BuildsTable({
  data,
  index,
  kits,
  kitIndex,
  kitGroups,
  rankToIndex,
  pageRows,
  selectedRank,
  pinned,
  onSelect,
  onSort,
  onTogglePin,
}: Props) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[900px] text-left text-sm">
        <thead className="border-b border-border bg-muted/45 text-[10px] uppercase tracking-[0.09em] text-muted-foreground">
          <tr>
            <th className="w-9 px-2" aria-label="Pin for comparison" />
            <th className="px-4 py-3">
              <button onClick={() => onSort('rank')}>Rank</button>
            </th>
            <th className="px-4 py-3">Build</th>
            <th className="px-4 py-3">Best kit</th>
            <th className="px-4 py-3">Levels</th>
            <th className="px-4 py-3">
              <button onClick={() => onSort('max_hit')}>Combat</button>
            </th>
            <th className="px-4 py-3">
              <button onClick={() => onSort('ko_12')}>12t KO</button>
            </th>
            <th className="px-4 py-3">
              <button onClick={() => onSort('defence')}>Defence</button>
            </th>
            <th className="px-4 py-3 text-right">
              <button onClick={() => onSort('score')}>Score</button>
            </th>
            <th className="w-10" aria-label="Open build details" />
          </tr>
        </thead>
        <tbody>
          {pageRows.map(({ row, equivalentCount }) => {
            const rowRank = numberAt(row, index, 'rank');
            const rowTier = stringAt(row, data.strings, index, 'tier');
            return (
              <tr
                key={`${rowRank}-${equivalentCount}`}
                tabIndex={0}
                aria-selected={selectedRank === rowRank}
                className={`cursor-pointer border-b border-border/65 transition-colors hover:bg-primary/6 focus-visible:bg-primary/8 focus-visible:outline-none ${selectedRank === rowRank ? 'bg-primary/9' : ''}`}
                onClick={() => onSelect(rowRank)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ')
                    onSelect(rowRank);
                }}
              >
                <td className="px-2">
                  <PinButton
                    pinned={pinned.includes(rowRank)}
                    enabled={canPinMore(pinned)}
                    label={`build #${rowRank}`}
                    onToggle={() => onTogglePin(rowRank)}
                  />
                </td>
                <td className="px-4 py-3.5">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-base font-semibold">
                      #{rowRank}
                    </span>
                    <Badge variant="outline" className={tierClasses(rowTier)}>
                      {rowTier}
                    </Badge>
                  </div>
                  {equivalentCount > 1 ? (
                    <p className="mt-1 text-[10px] text-primary">
                      {equivalentCount} equivalent profiles
                    </p>
                  ) : null}
                </td>
                <td className="max-w-[290px] px-4 py-3.5">
                  <p className="truncate font-medium">
                    {stringAt(row, data.strings, index, 'weapon')}
                  </p>
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {['head', 'neck', 'body']
                      .map((field) => stringAt(row, data.strings, index, field))
                      .join(' · ')}
                  </p>
                </td>
                <td className="px-4 py-3.5 font-mono text-xs">
                  <BestKitCell
                    kits={kits}
                    kitIndex={kitIndex}
                    kitRow={
                      kits
                        ? kitGroups.get(rankToIndex.get(rowRank) ?? -1)?.[0]
                        : undefined
                    }
                  />
                </td>
                <td className="px-4 py-3.5">
                  <div className="flex gap-1">
                    {levelPills.map(([label, field]) => (
                      <span key={field} className="level-pill">
                        <b>{label}</b>
                        {numberAt(row, index, field)}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3.5 font-mono text-xs">
                  <span className="font-semibold">
                    {numberAt(row, index, 'max_hit')} max
                  </span>
                  <span className="text-muted-foreground">
                    {' '}
                    · {numberAt(row, index, 'maximum_range')} tiles
                  </span>
                </td>
                <td className="px-4 py-3.5 font-mono text-xs">
                  {percentAt(row, index, 'ko_12').toFixed(1)}%
                </td>
                <td className="px-4 py-3.5 font-mono text-xs text-muted-foreground">
                  {defenceTotal(row, index)} total
                </td>
                <td className="px-4 py-3.5 text-right font-mono font-semibold text-primary">
                  {percentAt(row, index, 'score').toFixed(3)}
                </td>
                <td className="pr-3 text-muted-foreground">
                  <ChevronRight className="size-4" />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
