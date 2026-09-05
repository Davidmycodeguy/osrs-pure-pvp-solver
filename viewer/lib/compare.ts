// Pinning rows and laying them out side by side.
//
// A comparison reuses the columns the picker already has visible, so what you compare is what you
// chose to see. Each row of the comparison is one column; each cell is one pinned build or kit.

import {
  type ColumnContext,
  type KitColumn,
  columnText,
  columnValue,
  formatColumnValue,
} from '@/components/kit-columns';
import {
  type Dataset,
  type FieldIndex,
  SCALE,
  numberAt,
  stringAt,
} from '@/lib/dataset';

/** How many rows fit side by side before the panel stops being readable. */
export const MAX_PINNED = 4;

/**
 * Columns where a smaller number is the better one: the three rankings, the KO switch speed, and
 * the two slot costs. Everything else in KIT_COLUMNS reads better as it grows.
 */
const LOWER_IS_BETTER: ReadonlySet<string> = new Set([
  'rank',
  'pressure_rank',
  'build_rank',
  'ko_cooldown',
  'rune_slots',
  'switch_slots',
]);

export type CompareCell = { text: string; value: number | string };

export type CompareRow = {
  key: string;
  label: string;
  cells: CompareCell[];
  /** Indices of the cells holding the best value, empty when nothing wins. */
  bestIndices: number[];
  /** Whether the pinned rows disagree on this column at all. */
  differs: boolean;
};

/** A copy of `pinned` with `id` added or removed, capped at MAX_PINNED. */
export function togglePinned(pinned: readonly number[], id: number): number[] {
  if (pinned.includes(id)) return pinned.filter((each) => each !== id);
  if (pinned.length >= MAX_PINNED) return [...pinned];
  return [...pinned, id];
}

export function canPinMore(pinned: readonly number[]): boolean {
  return pinned.length < MAX_PINNED;
}

/** Which cells hold the winning value, or none when they are all equal or not numeric. */
export function bestCellIndices(key: string, cells: CompareCell[]): number[] {
  const numbers = cells.map((cell) =>
    typeof cell.value === 'number' ? cell.value : null,
  );
  if (numbers.some((value) => value === null)) return [];
  const values = numbers as number[];
  if (values.length < 2) return [];
  const lowerWins = LOWER_IS_BETTER.has(key);
  const best = lowerWins ? Math.min(...values) : Math.max(...values);
  if (values.every((value) => value === best)) return [];
  return values.flatMap((value, index) => (value === best ? [index] : []));
}

/** Whether the pinned rows disagree on a column. */
export function cellsDiffer(cells: CompareCell[]): boolean {
  return cells.some((cell) => cell.text !== cells[0]?.text);
}

/** One comparison row per column, in the columns' display order. */
export function buildCompareRows(
  columns: readonly KitColumn[],
  cellsFor: (column: KitColumn) => CompareCell[],
): CompareRow[] {
  return columns.map((column) => {
    const cells = cellsFor(column);
    return {
      key: column.key,
      label: column.label,
      cells,
      bestIndices: bestCellIndices(column.key, cells),
      differs: cellsDiffer(cells),
    };
  });
}

/** One pinned row's heading. */
export type CompareEntry = { id: number; title: string; subtitle: string };

export type CompareView = { entries: CompareEntry[]; rows: CompareRow[] };

/** A build column's cell, resolved without a kit row so the build views can compare too. */
function buildCell(
  column: KitColumn,
  row: number[],
  data: Dataset,
  index: FieldIndex,
): CompareCell {
  const value =
    column.kind === 'text'
      ? stringAt(row, data.strings, index, column.field)
      : numberAt(row, index, column.field);
  return { text: formatColumnValue(column, value, SCALE), value };
}

/** Pinned kits side by side, across every visible column. */
export function kitCompareView(
  pinned: readonly number[],
  columns: readonly KitColumn[],
  context: ColumnContext,
): CompareView {
  const { kits, kitIndex, data, buildIndex } = context;
  const rows = pinned.filter((kitRow) => kits.rows[kitRow] !== undefined);
  const entries = rows.map((kitRow) => {
    const kit = kits.rows[kitRow];
    const build = data.rows[numberAt(kit, kitIndex, 'build')];
    const switchWeapon = stringAt(kit, kits.strings, kitIndex, 'ko_weapon');
    return {
      id: kitRow,
      title: `Kit #${numberAt(kit, kitIndex, 'rank').toLocaleString()}`,
      subtitle: `${switchWeapon || 'No switch'} · build #${numberAt(build, buildIndex, 'rank').toLocaleString()}`,
    };
  });
  return {
    entries,
    rows: buildCompareRows(columns, (column) =>
      rows.map((kitRow) => {
        const kit = kits.rows[kitRow];
        const build = data.rows[numberAt(kit, kitIndex, 'build')];
        return {
          text: columnText(column, kit, build, context),
          value: columnValue(column, kit, build, context),
        };
      }),
    ),
  };
}

/**
 * Pinned builds side by side. Kit columns are dropped: without a chosen KO switch there is no kit
 * row to read them from.
 */
export function buildCompareView(
  pinnedRanks: readonly number[],
  columns: readonly KitColumn[],
  data: Dataset,
  index: FieldIndex,
  rankToIndex: ReadonlyMap<number, number>,
): CompareView {
  const rows = pinnedRanks
    .map((rank) => rankToIndex.get(rank))
    .filter((rowIndex): rowIndex is number => rowIndex !== undefined);
  const buildColumns = columns.filter((column) => column.source === 'build');
  const entries = rows.map((rowIndex) => {
    const row = data.rows[rowIndex];
    return {
      id: numberAt(row, index, 'rank'),
      title: `Build #${numberAt(row, index, 'rank').toLocaleString()}`,
      subtitle: stringAt(row, data.strings, index, 'weapon'),
    };
  });
  return {
    entries,
    rows: buildCompareRows(buildColumns, (column) =>
      rows.map((rowIndex) =>
        buildCell(column, data.rows[rowIndex], data, index),
      ),
    ),
  };
}
