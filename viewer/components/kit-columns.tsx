'use client';

import { useState, useSyncExternalStore } from 'react';
import { Columns3 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  type Dataset,
  type FieldIndex,
  type KitDataset,
  type RawRow,
  SCALE,
  numberAt,
  stringAt,
} from '@/lib/dataset';

type ColumnKind = 'int' | 'pct' | 'hundredths' | 'score' | 'text';
export type KitColumn = {
  key: string;
  label: string;
  source: 'kit' | 'build';
  field: string;
  kind: ColumnKind;
};

/** Every column the KO kits table can show, in display order. */
const KIT_COLUMNS: KitColumn[] = [
  {
    key: 'pressure_rank',
    label: 'Pressure rank (P#)',
    source: 'kit',
    field: 'pressure_rank',
    kind: 'int',
  },
  { key: 'rank', label: 'Kit rank', source: 'kit', field: 'rank', kind: 'int' },
  {
    key: 'tier',
    label: 'Attrition tier',
    source: 'kit',
    field: 'tier',
    kind: 'text',
  },
  {
    key: 'pressure',
    label: 'Beats one fish %',
    source: 'kit',
    field: 'pressure',
    kind: 'pct',
  },
  {
    key: 'bite',
    label: 'Bite +HP',
    source: 'kit',
    field: 'bite',
    kind: 'hundredths',
  },
  {
    key: 'max_burst',
    label: 'Max combo',
    source: 'kit',
    field: 'max_burst',
    kind: 'int',
  },
  {
    key: 'finish_10',
    label: 'Finish 10 %',
    source: 'kit',
    field: 'finish_10',
    kind: 'pct',
  },
  {
    key: 'finish_15',
    label: 'Finish 15 %',
    source: 'kit',
    field: 'finish_15',
    kind: 'pct',
  },
  {
    key: 'finish_20',
    label: 'Finish 20 %',
    source: 'kit',
    field: 'finish_20',
    kind: 'pct',
  },
  {
    key: 'ko_weapon',
    label: 'KO weapon',
    source: 'kit',
    field: 'ko_weapon',
    kind: 'text',
  },
  {
    key: 'ko_neck',
    label: 'KO amulet',
    source: 'kit',
    field: 'ko_neck',
    kind: 'text',
  },
  {
    key: 'ko_max_hit',
    label: 'KO max hit',
    source: 'kit',
    field: 'ko_max_hit',
    kind: 'int',
  },
  {
    key: 'ko_attack_roll',
    label: 'KO attack roll',
    source: 'kit',
    field: 'ko_attack_roll',
    kind: 'int',
  },
  {
    key: 'ko_cooldown',
    label: 'KO speed (ticks)',
    source: 'kit',
    field: 'ko_cooldown',
    kind: 'int',
  },
  {
    key: 'spell',
    label: 'Spell (runes)',
    source: 'kit',
    field: 'spell',
    kind: 'text',
  },
  {
    key: 'spell_max_hit',
    label: 'Spell max hit',
    source: 'kit',
    field: 'spell_max_hit',
    kind: 'int',
  },
  {
    key: 'rune_slots',
    label: 'Rune slots',
    source: 'kit',
    field: 'rune_slots',
    kind: 'int',
  },
  {
    key: 'switch_slots',
    label: 'Switch slots',
    source: 'kit',
    field: 'switch_slots',
    kind: 'int',
  },
  {
    key: 'food_slots',
    label: 'Food slots',
    source: 'kit',
    field: 'food_slots',
    kind: 'int',
  },
  {
    key: 'potions',
    label: 'Strength potions',
    source: 'kit',
    field: 'potions',
    kind: 'int',
  },
  {
    key: 'stack_15',
    label: 'Stack ≥15 %',
    source: 'kit',
    field: 'stack_15',
    kind: 'pct',
  },
  {
    key: 'stack_20',
    label: 'Stack ≥20 %',
    source: 'kit',
    field: 'stack_20',
    kind: 'pct',
  },
  {
    key: 'stack_30',
    label: 'Stack ≥30 %',
    source: 'kit',
    field: 'stack_30',
    kind: 'pct',
  },
  {
    key: 'switch_ko_4',
    label: 'Switch KO 4t %',
    source: 'kit',
    field: 'switch_ko_4',
    kind: 'pct',
  },
  {
    key: 'switch_ko_5',
    label: 'Switch KO 5t %',
    source: 'kit',
    field: 'switch_ko_5',
    kind: 'pct',
  },
  {
    key: 'switch_ko_8',
    label: 'Switch KO 8t %',
    source: 'kit',
    field: 'switch_ko_8',
    kind: 'pct',
  },
  {
    key: 'switch_ko_12',
    label: 'Switch KO 12t %',
    source: 'kit',
    field: 'switch_ko_12',
    kind: 'pct',
  },
  {
    key: 'ko_4',
    label: 'No-switch KO 4t %',
    source: 'build',
    field: 'ko_4',
    kind: 'pct',
  },
  {
    key: 'ko_5',
    label: 'No-switch KO 5t %',
    source: 'build',
    field: 'ko_5',
    kind: 'pct',
  },
  {
    key: 'ko_8',
    label: 'No-switch KO 8t %',
    source: 'build',
    field: 'ko_8',
    kind: 'pct',
  },
  {
    key: 'ko_12',
    label: 'No-switch KO 12t %',
    source: 'build',
    field: 'ko_12',
    kind: 'pct',
  },
  {
    key: 'dpt_low',
    label: 'DPT low def',
    source: 'build',
    field: 'dpt_low',
    kind: 'score',
  },
  {
    key: 'dpt_medium',
    label: 'DPT med def',
    source: 'build',
    field: 'dpt_medium',
    kind: 'score',
  },
  {
    key: 'dpt_high',
    label: 'DPT high def',
    source: 'build',
    field: 'dpt_high',
    kind: 'score',
  },
  {
    key: 'race_p3_mean_fish',
    label: 'Race mean fish',
    source: 'kit',
    field: 'race_p3_mean_fish',
    kind: 'hundredths',
  },
  {
    key: 'score',
    label: 'Kit score',
    source: 'kit',
    field: 'score',
    kind: 'pct',
  },
  {
    key: 'race_score',
    label: 'Race score',
    source: 'kit',
    field: 'race_score',
    kind: 'pct',
  },
  {
    key: 'ko_switch_score',
    label: 'KO switch score',
    source: 'kit',
    field: 'ko_switch_score',
    kind: 'pct',
  },
  {
    key: 'build_rank',
    label: 'Build rank',
    source: 'build',
    field: 'rank',
    kind: 'int',
  },
  {
    key: 'build_score',
    label: 'Build score',
    source: 'build',
    field: 'score',
    kind: 'pct',
  },
  {
    key: 'attack',
    label: 'Attack',
    source: 'build',
    field: 'attack',
    kind: 'int',
  },
  {
    key: 'strength',
    label: 'Strength',
    source: 'build',
    field: 'strength',
    kind: 'int',
  },
  {
    key: 'ranged',
    label: 'Ranged',
    source: 'build',
    field: 'ranged',
    kind: 'int',
  },
  {
    key: 'magic',
    label: 'Magic',
    source: 'build',
    field: 'magic',
    kind: 'int',
  },
  {
    key: 'prayer_level',
    label: 'Prayer',
    source: 'build',
    field: 'prayer_level',
    kind: 'int',
  },
  {
    key: 'defence',
    label: 'Def',
    source: 'build',
    field: 'defence_level',
    kind: 'int',
  },
  {
    key: 'hitpoints',
    label: 'HP',
    source: 'build',
    field: 'hitpoints',
    kind: 'int',
  },
  {
    key: 'weapon',
    label: 'Primary weapon',
    source: 'build',
    field: 'weapon',
    kind: 'text',
  },
  {
    key: 'max_hit',
    label: 'Primary max hit',
    source: 'build',
    field: 'max_hit',
    kind: 'int',
  },
  {
    key: 'maximum_attack_roll',
    label: 'Primary attack roll',
    source: 'build',
    field: 'maximum_attack_roll',
    kind: 'int',
  },
  { key: 'head', label: 'Head', source: 'build', field: 'head', kind: 'text' },
  { key: 'neck', label: 'Neck', source: 'build', field: 'neck', kind: 'text' },
  { key: 'body', label: 'Body', source: 'build', field: 'body', kind: 'text' },
  { key: 'legs', label: 'Legs', source: 'build', field: 'legs', kind: 'text' },
  {
    key: 'hands',
    label: 'Hands',
    source: 'build',
    field: 'hands',
    kind: 'text',
  },
  { key: 'ammo', label: 'Ammo', source: 'build', field: 'ammo', kind: 'text' },
];

const DEFAULT_COLUMNS: string[] = [
  'pressure_rank',
  'rank',
  'tier',
  'pressure',
  'bite',
  'max_burst',
  'finish_20',
  'ko_weapon',
  'ko_max_hit',
  'ko_cooldown',
  'spell',
  'food_slots',
  'stack_15',
  'switch_ko_8',
  'weapon',
  'attack',
  'strength',
  'ranged',
  'defence',
  'hitpoints',
  'score',
];

const STORAGE_KEY = 'purelab.kitColumns.v1';

export function columnByKey(key: string): KitColumn | undefined {
  return KIT_COLUMNS.find((column) => column.key === key);
}

export type ColumnContext = {
  kits: KitDataset;
  kitIndex: FieldIndex;
  data: Dataset;
  buildIndex: FieldIndex;
};

/** Raw sortable value: numbers as stored (already scaled), text as string. */
export function columnValue(
  column: KitColumn,
  kit: RawRow,
  build: RawRow,
  context: ColumnContext,
): number | string {
  if (column.source === 'kit') {
    if (column.kind === 'text') {
      const text = stringAt(
        kit,
        context.kits.strings,
        context.kitIndex,
        column.field,
      );
      if (column.field === 'spell') return text || '—';
      if (column.field === 'ko_weapon') {
        if (!text) return 'No switch';
        const neck = stringAt(
          kit,
          context.kits.strings,
          context.kitIndex,
          'ko_neck',
        );
        return neck ? `${text} + ${neck}` : text;
      }
      return text;
    }
    return numberAt(kit, context.kitIndex, column.field);
  }
  if (column.kind === 'text')
    return stringAt(
      build,
      context.data.strings,
      context.buildIndex,
      column.field,
    );
  return numberAt(build, context.buildIndex, column.field);
}

/** Display text for a cell (and the CSV export). */
export function columnText(
  column: KitColumn,
  kit: RawRow,
  build: RawRow,
  context: ColumnContext,
): string {
  const value = columnValue(column, kit, build, context);
  if (typeof value === 'string') return value;
  const scale = column.source === 'kit' ? context.kits.scale : SCALE;
  switch (column.kind) {
    case 'pct':
      return ((value / scale) * 100).toFixed(
        column.field === 'score' || column.field.endsWith('_score') ? 3 : 1,
      );
    case 'score':
      return (value / scale).toFixed(3);
    case 'hundredths':
      return (value / 100).toFixed(2);
    default:
      return value.toLocaleString();
  }
}

function loadStored(): string[] | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return null;
    const keys = parsed.filter(
      (key): key is string =>
        typeof key === 'string' && columnByKey(key) !== undefined,
    );
    return keys.length > 0 ? keys : null;
  } catch {
    return null;
  }
}

function store(keys: string[]) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(keys));
  } catch {
    // Storage may be unavailable (private mode, blocked site data); the choice just won't persist.
  }
}

/**
 * The stored selection as an external store, so the hook below can hand React a server snapshot
 * that matches the SSR HTML and the browser's own value only after hydration. `snapshot` is cached
 * because getSnapshot has to be referentially stable between renders.
 */
let snapshot: string[] | null = null;
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): string[] {
  snapshot ??= loadStored() ?? DEFAULT_COLUMNS;
  return snapshot;
}

/** The SSR HTML only ever knows DEFAULT_COLUMNS, so the hydration render must agree. */
function getServerSnapshot(): string[] {
  return DEFAULT_COLUMNS;
}

function publish(keys: string[]) {
  snapshot = keys;
  store(keys);
  for (const listener of listeners) listener();
}

/** Visible column keys, remembered per browser. */
export function useVisibleColumns(): [string[], (next: string[]) => void] {
  const keys = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const update = (next: string[]) => {
    const ordered = KIT_COLUMNS.map((column) => column.key).filter((key) =>
      next.includes(key),
    );
    publish(ordered);
  };
  return [keys, update];
}

type PickerProps = {
  visible: string[];
  onChange: (next: string[]) => void;
};

export function ColumnPicker({ visible, onChange }: PickerProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <Button
        size="sm"
        variant={open ? 'default' : 'outline'}
        onClick={() => setOpen((value) => !value)}
      >
        <Columns3 /> Columns ({visible.length})
      </Button>
      {open ? (
        <div className="absolute right-0 z-20 mt-2 w-[520px] max-w-[90vw] rounded-lg border border-border bg-card p-3 shadow-xl">
          <div className="mb-2 flex items-center justify-between text-xs">
            <span className="font-semibold">Show columns</span>
            <span className="flex gap-2">
              <button
                className="text-primary"
                onClick={() =>
                  onChange(KIT_COLUMNS.map((column) => column.key))
                }
              >
                all
              </button>
              <button
                className="text-primary"
                onClick={() => onChange(DEFAULT_COLUMNS)}
              >
                default
              </button>
              <button
                className="text-muted-foreground"
                onClick={() => setOpen(false)}
              >
                close
              </button>
            </span>
          </div>
          <div className="grid max-h-80 grid-cols-2 gap-x-3 gap-y-1 overflow-y-auto text-xs sm:grid-cols-3">
            {KIT_COLUMNS.map((column) => {
              const checked = visible.includes(column.key);
              return (
                <label
                  key={column.key}
                  className="flex cursor-pointer items-center gap-2 py-0.5"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() =>
                      onChange(
                        checked
                          ? visible.filter((key) => key !== column.key)
                          : [...visible, column.key],
                      )
                    }
                  />
                  <span
                    className={
                      column.source === 'build' ? 'text-muted-foreground' : ''
                    }
                  >
                    {column.label}
                  </span>
                </label>
              );
            })}
          </div>
          <p className="mt-2 text-[10px] text-muted-foreground">
            Grey labels come from the single-weapon build; the rest are per kit.
            Remembered in this browser.
          </p>
        </div>
      ) : null}
    </div>
  );
}

export const COPY_CAP = 50_000;

function csvCell(text: string) {
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

/** Visible columns as a CSV string for the given kit rows (capped). */
export function rowsAsCsv(
  columns: KitColumn[],
  kitRows: number[],
  context: ColumnContext,
): { csv: string; rows: number } {
  const limited = kitRows.slice(0, COPY_CAP);
  const lines = [columns.map((column) => csvCell(column.label)).join(',')];
  for (const kitRow of limited) {
    const kit = context.kits.rows[kitRow];
    const build = context.data.rows[numberAt(kit, context.kitIndex, 'build')];
    lines.push(
      columns
        .map((column) => csvCell(columnText(column, kit, build, context)))
        .join(','),
    );
  }
  return { csv: lines.join('\n'), rows: limited.length };
}
