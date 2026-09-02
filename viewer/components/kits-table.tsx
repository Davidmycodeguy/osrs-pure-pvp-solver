'use client';

import { ChevronRight } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import {
  type ColumnContext,
  type KitColumn,
  columnText,
  columnValue,
} from '@/components/kit-columns';
import { numberAt, tierClasses } from '@/lib/dataset';

/** Any kit column key; the page resolves it through KIT_COLUMNS. */
export type KitSortKey = string;

type Props = ColumnContext & {
  /** Visible columns in display order. */
  columns: KitColumn[];
  /** Kit row indices for the current page, already filtered and sorted. */
  pageRows: number[];
  selectedKit: number | null;
  sortKey: KitSortKey;
  sortDescending: boolean;
  onSelect: (kitIndex: number) => void;
  onSort: (key: KitSortKey) => void;
};

function Cell({
  column,
  text,
  value,
}: {
  column: KitColumn;
  text: string;
  value: number | string;
}) {
  if (column.key === 'tier') {
    return (
      <Badge variant="outline" className={tierClasses(String(value))}>
        {String(value)}
      </Badge>
    );
  }
  if (column.key === 'ko_weapon') {
    const baseline = value === 'No switch';
    return (
      <span
        className={`font-medium ${baseline ? 'text-muted-foreground' : 'text-primary'}`}
      >
        {text}
      </span>
    );
  }
  if (column.key === 'pressure') {
    return (
      <span
        className={`font-semibold ${typeof value === 'number' && value > 0 ? 'text-emerald-300' : 'text-muted-foreground'}`}
      >
        {text}%
      </span>
    );
  }
  if (column.kind === 'pct' && column.key !== 'score') return <>{text}%</>;
  if (column.key === 'score')
    return <span className="font-semibold text-primary">{text}</span>;
  if (column.key === 'pressure_rank' || column.key === 'rank')
    return <span className="font-semibold">#{text}</span>;
  return <>{text}</>;
}

export function KitsTable({
  kits,
  kitIndex,
  data,
  buildIndex,
  columns,
  pageRows,
  selectedKit,
  sortKey,
  sortDescending,
  onSelect,
  onSort,
}: Props) {
  const context: ColumnContext = { kits, kitIndex, data, buildIndex };
  return (
    <div className="overflow-x-auto">
      <table
        className="w-full text-left text-sm"
        style={{ fontVariantNumeric: 'tabular-nums' }}
      >
        <thead className="border-b border-border bg-muted/45 text-[10px] uppercase tracking-[0.09em] text-muted-foreground">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                className={`whitespace-nowrap px-3 py-3 ${column.kind === 'text' ? '' : 'text-right'}`}
              >
                <button
                  onClick={() => onSort(column.key)}
                  className={sortKey === column.key ? 'text-primary' : ''}
                >
                  {column.label}
                  {sortKey === column.key ? (sortDescending ? ' ▼' : ' ▲') : ''}
                </button>
              </th>
            ))}
            <th className="w-8" aria-label="Open kit details" />
          </tr>
        </thead>
        <tbody>
          {pageRows.map((kitRow) => {
            const kit = kits.rows[kitRow];
            const build = data.rows[numberAt(kit, kitIndex, 'build')];
            return (
              <tr
                key={kitRow}
                tabIndex={0}
                aria-selected={selectedKit === kitRow}
                className={`cursor-pointer border-b border-border/65 transition-colors hover:bg-primary/6 focus-visible:bg-primary/8 focus-visible:outline-none ${selectedKit === kitRow ? 'bg-primary/9' : ''}`}
                onClick={() => onSelect(kitRow)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ')
                    onSelect(kitRow);
                }}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={`max-w-[220px] truncate px-3 py-2.5 font-mono text-xs ${column.kind === 'text' ? '' : 'text-right'}`}
                  >
                    <Cell
                      column={column}
                      text={columnText(column, kit, build, context)}
                      value={columnValue(column, kit, build, context)}
                    />
                  </td>
                ))}
                <td className="pr-2 text-muted-foreground">
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
