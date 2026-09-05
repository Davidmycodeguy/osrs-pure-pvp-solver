'use client';

import { Pin, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { MAX_PINNED, type CompareView } from '@/lib/compare';

type Props = {
  view: CompareView;
  /** True while only rows that differ are shown. */
  differencesOnly: boolean;
  onToggleDifferencesOnly: () => void;
  onUnpin: (id: number) => void;
  onClear: () => void;
};

/** The empty state, so the pin button has something to explain itself with. */
export function ComparePlaceholder() {
  return (
    <p className="text-xs text-muted-foreground">
      Pin up to {MAX_PINNED} rows with the <Pin className="inline size-3" /> pin
      to compare them side by side. The comparison shows the columns you have
      visible.
    </p>
  );
}

/**
 * Pinned rows in adjacent columns, one comparison row per visible column. The best value in each
 * row is highlighted; rows every pinned entry agrees on can be hidden.
 */
export function ComparePanel({
  view,
  differencesOnly,
  onToggleDifferencesOnly,
  onUnpin,
  onClear,
}: Props) {
  const { entries, rows } = view;
  const shown = differencesOnly ? rows.filter((row) => row.differs) : rows;
  const hidden = rows.length - shown.length;
  return (
    <div className="panel mt-4 min-w-0 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border p-4">
        <div>
          <h2 className="font-semibold">Compare</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {entries.length} pinned · best value in each row is highlighted
            {hidden > 0 ? ` · ${hidden} identical rows hidden` : ''}
          </p>
        </div>
        <div className="flex gap-1.5">
          <Button
            size="sm"
            variant={differencesOnly ? 'default' : 'outline'}
            onClick={onToggleDifferencesOnly}
          >
            Differences only
          </Button>
          <Button size="sm" variant="outline" onClick={onClear}>
            Clear pins
          </Button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table
          className="w-full text-left text-sm"
          style={{ fontVariantNumeric: 'tabular-nums' }}
        >
          <thead className="border-b border-border bg-muted/45 text-[10px] uppercase tracking-[0.09em] text-muted-foreground">
            <tr>
              <th className="px-3 py-3">Stat</th>
              {entries.map((entry) => (
                <th key={entry.id} className="px-3 py-3 text-right">
                  <span className="flex items-center justify-end gap-1.5">
                    <span className="min-w-0">
                      <span className="block truncate text-xs font-semibold normal-case tracking-normal text-foreground">
                        {entry.title}
                      </span>
                      <span className="block truncate normal-case tracking-normal">
                        {entry.subtitle}
                      </span>
                    </span>
                    <button
                      aria-label={`Unpin ${entry.title}`}
                      className="text-muted-foreground hover:text-foreground"
                      onClick={() => onUnpin(entry.id)}
                    >
                      <X className="size-3.5" />
                    </button>
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => (
              <tr key={row.key} className="border-b border-border/65">
                <td className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground">
                  {row.label}
                </td>
                {row.cells.map((cell, index) => (
                  <td
                    key={entries[index]?.id ?? index}
                    className={`max-w-[220px] truncate px-3 py-2 text-right font-mono text-xs ${
                      row.bestIndices.includes(index)
                        ? 'font-semibold text-emerald-300'
                        : row.differs
                          ? ''
                          : 'text-muted-foreground'
                    }`}
                  >
                    {cell.text}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {shown.length === 0 ? (
        <p className="p-4 text-xs text-muted-foreground">
          The pinned rows agree on every visible column.
        </p>
      ) : null}
    </div>
  );
}
