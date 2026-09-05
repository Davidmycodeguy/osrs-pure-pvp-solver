// Numeric min/max filters over the stat columns, shared by the build and kit tables.
//
// What the user typed is the state; the raw bounds the tables compare against are derived from it.
// Keeping the text authoritative means a half-typed "64." is not normalised back to "64" under the
// cursor. A bound is entered in the units the table displays (levels, percents, damage per tick)
// and converted to the dataset's raw integer encoding on the way in. Every filterable stat is an
// existing KIT_COLUMNS entry, which supplies the label, the source dataset and the scaling.

import { type KitColumn, columnByKey } from '@/components/kit-columns';
import { SCALE } from '@/lib/dataset';
import type { ViewMode } from '@/lib/filtering';

/** One stat's bounds in raw dataset units; `null` on an edge means unbounded there. */
export type StatRange = { min: number | null; max: number | null };

/** Raw bounds per column key. A key is absent when neither edge is set. */
export type StatRanges = Readonly<Record<string, StatRange>>;

/** What the user typed, per column key. This is the state the panel is controlled by. */
export type StatInputs = Readonly<Record<string, { min: string; max: string }>>;

export type StatEdge = 'min' | 'max';

export type StatFilterGroup = { label: string; keys: readonly string[] };

const EMPTY_INPUT = { min: '', max: '' } as const;

/**
 * The stats that get input boxes, grouped the way the panel lays them out. Keys are KIT_COLUMNS
 * keys; a build-source key filters in every view, a kit-source key only in the kits view.
 */
export const STAT_FILTER_GROUPS: readonly StatFilterGroup[] = [
  {
    label: 'Combat levels',
    keys: [
      'attack',
      'strength',
      'ranged',
      'magic',
      'prayer_level',
      'defence',
      'hitpoints',
    ],
  },
  {
    label: 'Damage output',
    keys: [
      'max_hit',
      'ko_max_hit',
      'max_burst',
      'ko_4',
      'ko_12',
      'switch_ko_12',
      'dpt_low',
      'dpt_medium',
      'dpt_high',
    ],
  },
] as const;

/** The stat keys that can be filtered in a view; kit stats need the kit dataset. */
export function statFilterKeys(viewMode: ViewMode): string[] {
  const keys = STAT_FILTER_GROUPS.flatMap((group) => [...group.keys]);
  if (viewMode === 'kits') return keys;
  return keys.filter((key) => columnByKey(key)?.source === 'build');
}

/** The scale a column's raw value is stored at. */
function scaleOf(column: KitColumn, kitScale: number): number {
  return column.source === 'kit' ? kitScale : SCALE;
}

/** A typed box to a bound: blank or unparseable means "no bound". */
export function parseStatInput(text: string): number | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

/** Displayed units -> the dataset's raw integer encoding. */
export function displayToRaw(
  column: KitColumn,
  value: number,
  kitScale: number,
): number {
  switch (column.kind) {
    case 'pct':
      return (value / 100) * scaleOf(column, kitScale);
    case 'score':
      return value * scaleOf(column, kitScale);
    case 'hundredths':
      return value * 100;
    default:
      return value;
  }
}

/** A copy of `inputs` with one box changed; the key drops out once both boxes are empty. */
export function setStatInput(
  inputs: StatInputs,
  key: string,
  edge: StatEdge,
  text: string,
): StatInputs {
  const current = inputs[key] ?? EMPTY_INPUT;
  const next = { ...current, [edge]: text };
  const { [key]: _removed, ...rest } = inputs;
  if (!next.min.trim() && !next.max.trim()) return rest;
  return { ...rest, [key]: next };
}

/** The text in one stat's boxes, for a controlled input. */
export function statInputAt(
  inputs: StatInputs,
  key: string,
): { min: string; max: string } {
  return inputs[key] ?? EMPTY_INPUT;
}

export function clearStatInputs(): StatInputs {
  return {};
}

/** Typed boxes -> raw comparable bounds, dropping stats whose boxes say nothing usable. */
export function toStatRanges(inputs: StatInputs, kitScale: number): StatRanges {
  const ranges: Record<string, StatRange> = {};
  for (const [key, text] of Object.entries(inputs)) {
    const column = columnByKey(key);
    if (!column) continue;
    const min = parseStatInput(text.min);
    const max = parseStatInput(text.max);
    if (min === null && max === null) continue;
    ranges[key] = {
      min: min === null ? null : displayToRaw(column, min, kitScale),
      max: max === null ? null : displayToRaw(column, max, kitScale),
    };
  }
  return ranges;
}

/** How many stats carry at least one usable bound, for the panel's badge. */
export function activeStatCount(ranges: StatRanges): number {
  return Object.keys(ranges).length;
}

/** Whether a stat's two boxes describe an impossible range, so the panel can mark them. */
export function isInvertedInput(text: { min: string; max: string }): boolean {
  const min = parseStatInput(text.min);
  const max = parseStatInput(text.max);
  return min !== null && max !== null && min > max;
}

/**
 * Whether a row satisfies every bound. `read` returns the row's raw value for a stat key, or null
 * when the row cannot supply it — an unavailable stat is skipped rather than treated as zero, so a
 * kit-only bound never silently empties a build view.
 */
export function matchesStatRanges(
  ranges: StatRanges,
  read: (key: string) => number | null,
): boolean {
  for (const [key, range] of Object.entries(ranges)) {
    const value = read(key);
    if (value === null) continue;
    if (range.min !== null && value < range.min) return false;
    if (range.max !== null && value > range.max) return false;
  }
  return true;
}
