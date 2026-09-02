// Compact dictionary-encoded datasets written by scripts/export_build_data.py.

export type RawRow = number[];
export type FieldIndex = Record<string, number>;

export type Dataset = {
  version: number;
  count: number;
  fields: string[];
  strings: string[];
  rows: RawRow[];
  tierCounts: Record<string, number>;
};

export type KitDataset = {
  version: number;
  count: number;
  scale: number;
  fields: string[];
  strings: string[];
  rows: RawRow[];
  tierCounts: Record<string, number>;
};

export const SCALE = 1_000_000;
export const gearFields = [
  'head',
  'neck',
  'body',
  'legs',
  'hands',
  'weapon',
  'ammo',
  'shield',
] as const;

export function makeIndex(fields: string[]): FieldIndex {
  return Object.fromEntries(
    fields.map((field, index) => [field, index]),
  ) as FieldIndex;
}

export function numberAt(row: RawRow, index: FieldIndex, field: string) {
  return row[index[field]] ?? 0;
}

export function stringAt(
  row: RawRow,
  strings: string[],
  index: FieldIndex,
  field: string,
) {
  return strings[numberAt(row, index, field)] ?? '';
}

export function decimalAt(
  row: RawRow,
  index: FieldIndex,
  field: string,
  scale = SCALE,
) {
  return numberAt(row, index, field) / scale;
}

export function percentAt(
  row: RawRow,
  index: FieldIndex,
  field: string,
  scale = SCALE,
) {
  return decimalAt(row, index, field, scale) * 100;
}

export function tierClasses(tier: string) {
  const styles: Record<string, string> = {
    S: 'border-amber-300/30 bg-amber-300/12 text-amber-200',
    A: 'border-emerald-300/25 bg-emerald-300/10 text-emerald-200',
    B: 'border-sky-300/25 bg-sky-300/10 text-sky-200',
    N: 'border-violet-300/25 bg-violet-300/10 text-violet-200',
    C: 'border-zinc-400/25 bg-zinc-400/10 text-zinc-300',
  };
  return styles[tier] ?? styles.C;
}

/** Kit rows grouped by the build they extend, in kit-rank order. */
export function kitsByBuild(
  kits: KitDataset,
  index: FieldIndex,
): Map<number, number[]> {
  const groups = new Map<number, number[]>();
  kits.rows.forEach((row, kitIndex) => {
    const build = numberAt(row, index, 'build');
    const list = groups.get(build);
    if (list) list.push(kitIndex);
    else groups.set(build, [kitIndex]);
  });
  return groups;
}
