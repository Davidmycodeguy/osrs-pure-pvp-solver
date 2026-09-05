'use client';

import { RotateCcw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { type KitColumn, columnByKey } from '@/components/kit-columns';
import type { ViewMode } from '@/lib/filtering';
import {
  STAT_FILTER_GROUPS,
  type StatEdge,
  type StatInputs,
  isInvertedInput,
  statFilterKeys,
  statInputAt,
} from '@/lib/stat-filters';

type Props = {
  viewMode: ViewMode;
  inputs: StatInputs;
  /** How many stats currently narrow the table, for the clear button. */
  activeCount: number;
  onChange: (key: string, edge: StatEdge, text: string) => void;
  onClear: () => void;
};

function StatRow({
  column,
  text,
  onChange,
}: {
  column: KitColumn;
  text: { min: string; max: string };
  onChange: (key: string, edge: StatEdge, value: string) => void;
}) {
  const inverted = isInvertedInput(text);
  return (
    <div className="flex items-center gap-2">
      <label
        className="min-w-0 flex-1 truncate text-xs text-muted-foreground"
        htmlFor={`stat-${column.key}-min`}
      >
        {column.label}
      </label>
      {(['min', 'max'] as const).map((edge) => (
        <Input
          key={edge}
          id={`stat-${column.key}-${edge}`}
          type="number"
          inputMode="decimal"
          aria-label={`${column.label} ${edge === 'min' ? 'minimum' : 'maximum'}`}
          aria-invalid={inverted}
          placeholder={edge}
          className={`h-8 w-[4.75rem] px-2 text-right font-mono text-xs ${
            inverted ? 'border-red-400/70' : ''
          }`}
          value={text[edge]}
          onChange={(event) => onChange(column.key, edge, event.target.value)}
        />
      ))}
    </div>
  );
}

/**
 * Min/max boxes for the combat levels and the damage stats. Bounds are typed in the units the
 * table shows and are inclusive on both edges; a blank box means that edge is unbounded.
 */
export function StatFiltersPanel({
  viewMode,
  inputs,
  activeCount,
  onChange,
  onClear,
}: Props) {
  const available = new Set(statFilterKeys(viewMode));
  return (
    <div className="mt-3 rounded-lg border border-border bg-muted/25 p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Bounds are inclusive and use the units shown in the table. Leave a box
          empty for no limit.
        </p>
        <Button
          size="sm"
          variant="outline"
          disabled={activeCount === 0}
          onClick={onClear}
        >
          <RotateCcw /> Clear{activeCount > 0 ? ` (${activeCount})` : ''}
        </Button>
      </div>
      <div className="grid gap-x-8 gap-y-3 md:grid-cols-2">
        {STAT_FILTER_GROUPS.map((group) => {
          const keys = group.keys.filter((key) => available.has(key));
          if (keys.length === 0) return null;
          return (
            <fieldset key={group.label} className="min-w-0">
              <legend className="mb-1.5 text-[10px] uppercase tracking-[0.09em] text-muted-foreground">
                {group.label}
              </legend>
              <div className="flex flex-col gap-1.5">
                {keys.map((key) => {
                  const column = columnByKey(key);
                  if (!column) return null;
                  return (
                    <StatRow
                      key={key}
                      column={column}
                      text={statInputAt(inputs, key)}
                      onChange={onChange}
                    />
                  );
                })}
              </div>
            </fieldset>
          );
        })}
      </div>
      {viewMode !== 'kits' ? (
        <p className="mt-2.5 text-[11px] text-muted-foreground">
          KO max hit, max combo and switch KO only apply in the KO kits view.
        </p>
      ) : null}
    </div>
  );
}
