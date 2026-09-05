import { describe, expect, it } from 'vitest';

import { columnByKey } from '@/components/kit-columns';
import { SCALE } from '@/lib/dataset';
import {
  type StatInputs,
  activeStatCount,
  clearStatInputs,
  displayToRaw,
  isInvertedInput,
  matchesStatRanges,
  parseStatInput,
  setStatInput,
  statFilterKeys,
  statInputAt,
  toStatRanges,
} from '@/lib/stat-filters';

const KIT_SCALE = 10_000;

function column(key: string) {
  const found = columnByKey(key);
  if (!found) throw new Error(`no such column: ${key}`);
  return found;
}

describe('parseStatInput', () => {
  it('reads a blank box as "no bound"', () => {
    expect(parseStatInput('')).toBeNull();
    expect(parseStatInput('   ')).toBeNull();
  });

  it('reads a number', () => {
    expect(parseStatInput('70')).toBe(70);
    expect(parseStatInput('64.2')).toBe(64.2);
    expect(parseStatInput(' 12 ')).toBe(12);
  });

  it('rejects anything that is not a finite number', () => {
    expect(parseStatInput('abc')).toBeNull();
    expect(parseStatInput('7x')).toBeNull();
    expect(parseStatInput('Infinity')).toBeNull();
    expect(parseStatInput('NaN')).toBeNull();
  });
});

describe('displayToRaw', () => {
  it('leaves integer columns alone', () => {
    expect(displayToRaw(column('strength'), 70, KIT_SCALE)).toBe(70);
    expect(displayToRaw(column('max_hit'), 31, KIT_SCALE)).toBe(31);
  });

  it('scales a build percentage by the build scale', () => {
    // ko_12 is a build column, so it uses SCALE regardless of the kit scale.
    expect(displayToRaw(column('ko_12'), 64.2, KIT_SCALE)).toBeCloseTo(
      (64.2 / 100) * SCALE,
      6,
    );
  });

  it('scales a kit percentage by the kit scale', () => {
    expect(displayToRaw(column('switch_ko_12'), 25, KIT_SCALE)).toBeCloseTo(
      (25 / 100) * KIT_SCALE,
      6,
    );
  });

  it('scales score and hundredths columns', () => {
    expect(displayToRaw(column('dpt_medium'), 3.125, KIT_SCALE)).toBeCloseTo(
      3.125 * SCALE,
      6,
    );
    expect(displayToRaw(column('bite'), 4.5, KIT_SCALE)).toBeCloseTo(450, 6);
  });
});

describe('setStatInput', () => {
  it('does not mutate the inputs it is given', () => {
    const before: StatInputs = {};
    const after = setStatInput(before, 'strength', 'min', '70');
    expect(before).toEqual({});
    expect(after).toEqual({ strength: { min: '70', max: '' } });
  });

  it('keeps the text exactly as typed, mid-decimal included', () => {
    const inputs = setStatInput({}, 'ko_12', 'min', '64.');
    expect(statInputAt(inputs, 'ko_12').min).toBe('64.');
  });

  it('keeps the other edge when one is set', () => {
    const inputs = setStatInput(
      setStatInput({}, 'strength', 'min', '70'),
      'strength',
      'max',
      '75',
    );
    expect(statInputAt(inputs, 'strength')).toEqual({ min: '70', max: '75' });
  });

  it('drops the entry once both boxes are emptied', () => {
    const inputs = setStatInput(
      { strength: { min: '70', max: '' } },
      'strength',
      'min',
      '',
    );
    expect(inputs).toEqual({});
  });

  it('leaves other keys untouched', () => {
    const inputs = setStatInput(
      { attack: { min: '40', max: '' } },
      'strength',
      'min',
      '70',
    );
    expect(statInputAt(inputs, 'attack')).toEqual({ min: '40', max: '' });
  });
});

describe('statInputAt', () => {
  it('reports empty boxes for a stat with no bounds', () => {
    expect(statInputAt({}, 'strength')).toEqual({ min: '', max: '' });
  });
});

describe('toStatRanges', () => {
  it('converts typed levels straight through', () => {
    const ranges = toStatRanges(
      { strength: { min: '70', max: '75' } },
      KIT_SCALE,
    );
    expect(ranges.strength).toEqual({ min: 70, max: 75 });
  });

  it('scales a typed percentage into raw units', () => {
    const ranges = toStatRanges({ ko_12: { min: '64.2', max: '' } }, KIT_SCALE);
    expect(ranges.ko_12?.min).toBeCloseTo((64.2 / 100) * SCALE, 6);
    expect(ranges.ko_12?.max).toBeNull();
  });

  it('skips stats whose boxes hold nothing usable', () => {
    expect(
      toStatRanges({ strength: { min: 'abc', max: '' } }, KIT_SCALE),
    ).toEqual({});
    expect(toStatRanges({ strength: { min: '', max: '' } }, KIT_SCALE)).toEqual(
      {},
    );
  });

  it('skips a key that is not a known column', () => {
    expect(
      toStatRanges({ nonsense: { min: '1', max: '' } }, KIT_SCALE),
    ).toEqual({});
  });

  it('treats a half-typed decimal as its numeric prefix', () => {
    const ranges = toStatRanges(
      { strength: { min: '70.', max: '' } },
      KIT_SCALE,
    );
    expect(ranges.strength).toEqual({ min: 70, max: null });
  });
});

describe('activeStatCount', () => {
  it('counts the stats that have at least one bound', () => {
    expect(activeStatCount({})).toBe(0);
    expect(activeStatCount({ strength: { min: 70, max: null } })).toBe(1);
    expect(
      activeStatCount({
        strength: { min: 70, max: 75 },
        attack: { min: null, max: 50 },
      }),
    ).toBe(2);
  });
});

describe('isInvertedInput', () => {
  it('flags a minimum above the maximum', () => {
    expect(isInvertedInput({ min: '75', max: '60' })).toBe(true);
  });

  it('accepts a sane or half-filled range', () => {
    expect(isInvertedInput({ min: '60', max: '75' })).toBe(false);
    expect(isInvertedInput({ min: '60', max: '60' })).toBe(false);
    expect(isInvertedInput({ min: '75', max: '' })).toBe(false);
    expect(isInvertedInput({ min: '', max: '' })).toBe(false);
  });
});

describe('clearStatInputs', () => {
  it('returns an empty set of inputs', () => {
    expect(clearStatInputs()).toEqual({});
  });
});

describe('matchesStatRanges', () => {
  const read = (key: string) =>
    ({ strength: 70, attack: 40, ko_12: 500_000 })[key] ?? null;

  it('passes everything when no range is set', () => {
    expect(matchesStatRanges({}, read)).toBe(true);
  });

  it('applies an inclusive minimum', () => {
    expect(matchesStatRanges({ strength: { min: 70, max: null } }, read)).toBe(
      true,
    );
    expect(matchesStatRanges({ strength: { min: 71, max: null } }, read)).toBe(
      false,
    );
  });

  it('applies an inclusive maximum', () => {
    expect(matchesStatRanges({ strength: { min: null, max: 70 } }, read)).toBe(
      true,
    );
    expect(matchesStatRanges({ strength: { min: null, max: 69 } }, read)).toBe(
      false,
    );
  });

  it('requires every stat to match', () => {
    const ranges = {
      strength: { min: 70, max: null },
      attack: { min: 60, max: null },
    };
    expect(matchesStatRanges(ranges, read)).toBe(false);
  });

  it('ignores a stat the row cannot supply', () => {
    expect(matchesStatRanges({ ko_max_hit: { min: 5, max: null } }, read)).toBe(
      true,
    );
  });

  it('never matches when the range is inverted', () => {
    expect(matchesStatRanges({ strength: { min: 75, max: 60 } }, read)).toBe(
      false,
    );
  });
});

describe('statFilterKeys', () => {
  it('offers every listed stat in the kits view', () => {
    const keys = statFilterKeys('kits');
    expect(keys).toContain('strength');
    expect(keys).toContain('ko_max_hit');
  });

  it('drops kit-only stats in the build views', () => {
    const keys = statFilterKeys('profiles');
    expect(keys).toContain('strength');
    expect(keys).not.toContain('ko_max_hit');
  });

  it('only names columns that exist', () => {
    for (const key of statFilterKeys('kits')) {
      expect(columnByKey(key)).toBeDefined();
    }
  });
});
