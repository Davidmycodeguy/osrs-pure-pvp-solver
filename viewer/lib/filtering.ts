// Pure filtering, grouping and sorting helpers shared by the build and kit tables.

import {
  type ColumnContext,
  columnByKey,
  columnValue,
} from '@/components/kit-columns';
import {
  type Dataset,
  type FieldIndex,
  type KitDataset,
  type RawRow,
  gearFields,
  makeIndex,
  numberAt,
  stringAt,
} from '@/lib/dataset';

export type SortKey = 'rank' | 'score' | 'max_hit' | 'ko_12' | 'defence';
export type ViewMode = 'envelopes' | 'profiles' | 'kits';
export type ViewRow = { row: RawRow; equivalentCount: number };
export type RankMode = 'attrition' | 'pressure';

export const PAGE_SIZE = 50;
export const tierOrder = ['All', 'S', 'A', 'B', 'N', 'C'];
export const ALL_WEAPONS = 'All weapons';
export const ALL_KO = 'All KO weapons';
export const NO_SWITCH = 'No switch';

/** Two builds that agree on every one of these fields fight identically. */
const envelopeFields = [
  ...gearFields,
  'weapon_type',
  'maximum_attack_roll',
  'max_hit',
  'potted_max_hit',
  'maximum_range',
  'defence_stab_roll',
  'defence_slash_roll',
  'defence_crush_roll',
  'defence_ranged_roll',
  'magic',
  'prayer_level',
  'defence_level',
  'hitpoints',
  'dpt_low',
  'dpt_medium',
  'dpt_high',
] as const;

const defenceFields = [
  'defence_stab',
  'defence_slash',
  'defence_crush',
  'defence_magic',
  'defence_ranged',
];

/** Filters shared by the build views; `query` is already trimmed and lower-cased. */
type BuildFilters = {
  tier: string;
  weaponType: string;
  seedOnly: boolean;
  query: string;
};

export type KitFilters = BuildFilters & { koWeapon: string };

function envelopeKey(row: RawRow, index: FieldIndex) {
  return envelopeFields.map((field) => numberAt(row, index, field)).join(':');
}

export function prettyReason(value: string) {
  return value
    .replace(/^strong_category:/, 'Strong ')
    .replace(/^damage_type_representative:/, '')
    .replaceAll('_', ' ')
    .replace(/\bko\b/gi, 'KO')
    .replace(/^./, (letter) => letter.toUpperCase());
}

function buildSearchText(row: RawRow, data: Dataset, index: FieldIndex) {
  return [
    `#${numberAt(row, index, 'rank')}`,
    stringAt(row, data.strings, index, 'candidate_id'),
    ...gearFields.map((field) => stringAt(row, data.strings, index, field)),
    stringAt(row, data.strings, index, 'weapon_type'),
  ]
    .join(' ')
    .toLowerCase();
}

/** Sum of the five defence bonuses of the worn gear. */
export function defenceTotal(row: RawRow, index: FieldIndex) {
  return defenceFields.reduce(
    (total, field) => total + numberAt(row, index, field),
    0,
  );
}

/** Which of the two kit rankings a kit sort key belongs to. */
export function rankModeOf(kitSortKey: string): RankMode {
  return kitSortKey === 'pressure_rank' || kitSortKey === 'pressure'
    ? 'pressure'
    : 'attrition';
}

export function listWeaponTypes(data: Dataset, index: FieldIndex): string[] {
  return Array.from(
    new Set(
      data.rows.map((row) => stringAt(row, data.strings, index, 'weapon_type')),
    ),
  )
    .filter(Boolean)
    .sort();
}

export function listKoWeapons(
  kits: KitDataset,
  kitIndex: FieldIndex,
): string[] {
  const seen = new Set<string>();
  for (const row of kits.rows) {
    const name = stringAt(row, kits.strings, kitIndex, 'ko_weapon');
    if (name) seen.add(name);
  }
  return Array.from(seen).sort();
}

/** Build rank -> row index, for datasets whose rows are not in rank order. */
export function rankIndex(
  data: Dataset | null,
  index: FieldIndex,
): Map<number, number> {
  const map = new Map<number, number>();
  if (data)
    data.rows.forEach((row, i) => map.set(numberAt(row, index, 'rank'), i));
  return map;
}

/** Build rank of the first kit row, so the panel can open on the top kit. */
export function firstKitBuildRank(kits: KitDataset, builds: Dataset) {
  const kitFields = makeIndex(kits.fields);
  const buildFields = makeIndex(builds.fields);
  return numberAt(
    builds.rows[numberAt(kits.rows[0], kitFields, 'build')],
    buildFields,
    'rank',
  );
}

/** How many rows (including `selected` itself) share the selected build's envelope. */
export function countEnvelopeTwins(
  data: Dataset,
  index: FieldIndex,
  selected: RawRow,
) {
  const key = envelopeKey(selected, index);
  let count = 0;
  for (const row of data.rows) if (envelopeKey(row, index) === key) count += 1;
  return count;
}

function matchesBuild(
  row: RawRow,
  data: Dataset,
  index: FieldIndex,
  filters: BuildFilters,
) {
  if (
    filters.tier !== 'All' &&
    stringAt(row, data.strings, index, 'tier') !== filters.tier
  )
    return false;
  if (
    filters.weaponType !== ALL_WEAPONS &&
    stringAt(row, data.strings, index, 'weapon_type') !== filters.weaponType
  )
    return false;
  if (filters.seedOnly && numberAt(row, index, 'simulator_seed') !== 1)
    return false;
  if (
    filters.query &&
    !buildSearchText(row, data, index).includes(filters.query)
  )
    return false;
  return true;
}

function groupEnvelopes(rows: RawRow[], index: FieldIndex): ViewRow[] {
  const groups = new Map<string, ViewRow>();
  for (const row of rows) {
    const key = envelopeKey(row, index);
    const existing = groups.get(key);
    if (existing) existing.equivalentCount += 1;
    else groups.set(key, { row, equivalentCount: 1 });
  }
  return Array.from(groups.values());
}

function sortBuildRows(
  rows: ViewRow[],
  index: FieldIndex,
  sortKey: SortKey,
  descending: boolean,
): ViewRow[] {
  const sortValue = (row: RawRow) =>
    sortKey === 'defence'
      ? defenceTotal(row, index)
      : numberAt(row, index, sortKey);
  return [...rows].sort((left, right) => {
    const delta = sortValue(left.row) - sortValue(right.row);
    if (delta !== 0) return descending ? -delta : delta;
    return (
      numberAt(left.row, index, 'rank') - numberAt(right.row, index, 'rank')
    );
  });
}

/** Builds that pass the filters, one row per envelope when `grouped`, in sort order. */
export function filterBuilds(
  data: Dataset,
  index: FieldIndex,
  filters: BuildFilters,
  grouped: boolean,
  sortKey: SortKey,
  descending: boolean,
): ViewRow[] {
  const matches = data.rows.filter((row) =>
    matchesBuild(row, data, index, filters),
  );
  const viewed = grouped
    ? groupEnvelopes(matches, index)
    : matches.map((row) => ({ row, equivalentCount: 1 }));
  return sortBuildRows(viewed, index, sortKey, descending);
}

function matchesKit(kit: RawRow, context: ColumnContext, filters: KitFilters) {
  const { kits, kitIndex, data, buildIndex } = context;
  if (
    filters.tier !== 'All' &&
    stringAt(kit, kits.strings, kitIndex, 'tier') !== filters.tier
  )
    return false;
  const baseline = numberAt(kit, kitIndex, 'baseline') === 1;
  if (filters.koWeapon === NO_SWITCH && !baseline) return false;
  if (
    filters.koWeapon !== ALL_KO &&
    filters.koWeapon !== NO_SWITCH &&
    stringAt(kit, kits.strings, kitIndex, 'ko_weapon') !== filters.koWeapon
  )
    return false;
  const build = data.rows[numberAt(kit, kitIndex, 'build')];
  if (
    filters.weaponType !== ALL_WEAPONS &&
    stringAt(build, data.strings, buildIndex, 'weapon_type') !==
      filters.weaponType
  )
    return false;
  if (filters.seedOnly && numberAt(build, buildIndex, 'simulator_seed') !== 1)
    return false;
  if (filters.query) {
    const text = `${buildSearchText(build, data, buildIndex)} ${stringAt(kit, kits.strings, kitIndex, 'ko_weapon').toLowerCase()} kit#${numberAt(kit, kitIndex, 'rank')}`;
    if (!text.includes(filters.query)) return false;
  }
  return true;
}

function sortKitRows(
  matches: number[],
  context: ColumnContext,
  sortKey: string,
  descending: boolean,
): number[] {
  if (sortKey === 'rank' && !descending) return matches;
  const column = columnByKey(sortKey) ?? columnByKey('rank');
  if (!column) return matches;
  const { kits, kitIndex, data } = context;
  const value = (kitRow: number) => {
    const kit = kits.rows[kitRow];
    return columnValue(
      column,
      kit,
      data.rows[numberAt(kit, kitIndex, 'build')],
      context,
    );
  };
  return [...matches].sort((left, right) => {
    const a = value(left);
    const b = value(right);
    const delta =
      typeof a === 'number' && typeof b === 'number'
        ? a - b
        : String(a).localeCompare(String(b));
    if (delta !== 0) return descending ? -delta : delta;
    return (
      numberAt(kits.rows[left], kitIndex, 'rank') -
      numberAt(kits.rows[right], kitIndex, 'rank')
    );
  });
}

/** Kit row indices that pass the filters, in sort order. */
export function filterKits(
  context: ColumnContext,
  filters: KitFilters,
  sortKey: string,
  descending: boolean,
): number[] {
  const matches: number[] = [];
  context.kits.rows.forEach((kit, kitRow) => {
    if (matchesKit(kit, context, filters)) matches.push(kitRow);
  });
  return sortKitRows(matches, context, sortKey, descending);
}
