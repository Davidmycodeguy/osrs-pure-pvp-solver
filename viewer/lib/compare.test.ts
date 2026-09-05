import { describe, expect, it } from 'vitest';

import { type KitColumn, columnByKey } from '@/components/kit-columns';
import {
  MAX_PINNED,
  type CompareCell,
  bestCellIndices,
  buildCompareRows,
  canPinMore,
  cellsDiffer,
  togglePinned,
} from '@/lib/compare';

const cells = (...values: Array<number | string>): CompareCell[] =>
  values.map((value) => ({ text: String(value), value }));

describe('togglePinned', () => {
  it('pins a row that is not pinned yet', () => {
    expect(togglePinned([], 7)).toEqual([7]);
    expect(togglePinned([1], 7)).toEqual([1, 7]);
  });

  it('unpins a row that is already pinned', () => {
    expect(togglePinned([1, 7], 7)).toEqual([1]);
  });

  it('does not mutate the list it is given', () => {
    const before = [1, 2];
    const after = togglePinned(before, 3);
    expect(before).toEqual([1, 2]);
    expect(after).toEqual([1, 2, 3]);
  });

  it('refuses to pin past the cap', () => {
    const full = [1, 2, 3, 4];
    expect(full).toHaveLength(MAX_PINNED);
    expect(togglePinned(full, 5)).toEqual(full);
  });

  it('still unpins when the list is full', () => {
    expect(togglePinned([1, 2, 3, 4], 2)).toEqual([1, 3, 4]);
  });

  it('keeps pin order rather than sorting', () => {
    expect(togglePinned(togglePinned([], 9), 3)).toEqual([9, 3]);
  });
});

describe('canPinMore', () => {
  it('is true below the cap and false at it', () => {
    expect(canPinMore([])).toBe(true);
    expect(canPinMore([1, 2, 3])).toBe(true);
    expect(canPinMore([1, 2, 3, 4])).toBe(false);
  });
});

describe('bestCellIndices', () => {
  it('picks the largest value for a normal column', () => {
    expect(bestCellIndices('max_hit', cells(28, 31, 30))).toEqual([1]);
  });

  it('picks the smallest value for a ranking column', () => {
    expect(bestCellIndices('rank', cells(12, 3, 40))).toEqual([1]);
  });

  it('treats the KO switch speed as lower-is-better', () => {
    expect(bestCellIndices('ko_cooldown', cells(5, 4))).toEqual([1]);
  });

  it('marks every cell that ties for the win', () => {
    expect(bestCellIndices('max_hit', cells(31, 31, 28))).toEqual([0, 1]);
  });

  it('marks nothing when every cell is equal', () => {
    expect(bestCellIndices('max_hit', cells(30, 30))).toEqual([]);
  });

  it('marks nothing for text columns', () => {
    expect(
      bestCellIndices('weapon', cells('Rune scimitar', 'Maple bow')),
    ).toEqual([]);
  });

  it('marks nothing when only one row is pinned', () => {
    expect(bestCellIndices('max_hit', cells(31))).toEqual([]);
  });
});

describe('cellsDiffer', () => {
  it('is false when the pinned rows agree', () => {
    expect(cellsDiffer(cells(30, 30, 30))).toBe(false);
  });

  it('is true as soon as one differs', () => {
    expect(cellsDiffer(cells(30, 31, 30))).toBe(true);
  });

  it('compares the displayed text, not the raw value', () => {
    expect(
      cellsDiffer([
        { text: '64.2', value: 642_000 },
        { text: '64.2', value: 642_001 },
      ]),
    ).toBe(false);
  });
});

describe('buildCompareRows', () => {
  const columns = ['rank', 'strength', 'max_hit']
    .map((key) => columnByKey(key))
    .filter((column): column is KitColumn => column !== undefined);

  it('makes one row per column, in order', () => {
    const rows = buildCompareRows(columns, () => cells(1, 2));
    expect(rows.map((row) => row.key)).toEqual(['rank', 'strength', 'max_hit']);
  });

  it('carries the column label through', () => {
    const rows = buildCompareRows(columns, () => cells(1, 2));
    expect(rows[0].label).toBe(columnByKey('rank')?.label);
  });

  it('resolves the winner per column direction', () => {
    const rows = buildCompareRows(columns, (column) =>
      column.key === 'rank' ? cells(5, 2) : cells(70, 75),
    );
    expect(rows[0].bestIndices).toEqual([1]);
    expect(rows[1].bestIndices).toEqual([1]);
  });

  it('flags the rows the pinned entries disagree on', () => {
    const rows = buildCompareRows(columns, (column) =>
      column.key === 'strength' ? cells(70, 70) : cells(1, 2),
    );
    expect(rows.map((row) => row.differs)).toEqual([true, false, true]);
  });

  it('returns nothing when no columns are visible', () => {
    expect(buildCompareRows([], () => [])).toEqual([]);
  });
});
