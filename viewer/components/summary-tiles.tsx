'use client';

import { BarChart3, Database, Info, Shield, Swords } from 'lucide-react';

import {
  type Dataset,
  type FieldIndex,
  type KitDataset,
  numberAt,
} from '@/lib/dataset';

type Props = {
  level: number;
  data: Dataset | null;
  kits: KitDataset | null;
  index: FieldIndex;
};

/** The four headline counters and the model-scope banner under the header. */
export function SummaryTiles({ level, data, kits, index }: Props) {
  return (
    <>
      <section className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ['Builds', data?.count.toLocaleString() ?? '…', Database],
          ['KO kits', kits ? kits.count.toLocaleString() : '…', Swords],
          [
            'S tier builds',
            data?.tierCounts.S?.toLocaleString() ?? '…',
            BarChart3,
          ],
          [
            `Exact CB${level} accounts`,
            data
              ? new Set(
                  data.rows.map((row) => numberAt(row, index, 'profile_id')),
                ).size.toLocaleString()
              : '…',
            Shield,
          ],
        ].map(([label, value, Icon]) => (
          <div key={String(label)} className="metric-card">
            <Icon className="size-4 text-primary" />
            <div>
              <p className="text-xs text-muted-foreground">{String(label)}</p>
              <p className="mt-0.5 font-mono text-xl font-semibold">
                {String(value)}
              </p>
            </div>
          </div>
        ))}
      </section>

      <div className="mb-4 flex items-start gap-2 rounded-lg border border-sky-400/15 bg-sky-400/6 px-3 py-2.5 text-xs text-sky-100/80">
        <Info className="mt-0.5 size-4 shrink-0 text-sky-300" />
        <p>
          Every build is an exact account at combat level {level} (Defence 1 to
          40 at level 40) wearing its offence-optimal single-weapon kit. The KO
          kits view adds one row per carried melee switch that out-hits the
          primary: an exact arrow-plus-KO stack, switch cadence KO, and a race
          with food reduced by the switch. Movement, projectile flight, potions
          and policy still wait for the simulator.
        </p>
      </div>
    </>
  );
}
