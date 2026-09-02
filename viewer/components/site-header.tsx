'use client';

import { Database, Swords } from 'lucide-react';

import type { Dataset, KitDataset } from '@/lib/dataset';

type Props = {
  level: number;
  data: Dataset | null;
  kits: KitDataset | null;
  onLevelChange: (level: number) => void;
};

/** Sticky page header: brand, combat-level select and dataset counters. */
export function SiteHeader({ level, data, kits, onLevelChange }: Props) {
  return (
    <header className="sticky top-0 z-30 border-b border-border/80 bg-card/85 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1680px] items-center justify-between gap-5 px-4 py-3 sm:px-6 lg:px-8">
        <div className="flex items-center gap-3">
          <div className="grid size-10 place-items-center rounded-xl border border-primary/30 bg-primary/12 text-primary">
            <Swords className="size-5" />
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-primary">
              PureLab
            </p>
            <h1 className="text-base font-semibold tracking-tight sm:text-lg">
              F2P build explorer
            </h1>
          </div>
        </div>
        <div className="hidden items-center gap-2 text-xs text-muted-foreground md:flex">
          <select
            aria-label="Combat level"
            className="h-8 rounded-lg border border-border bg-background px-2 text-xs text-foreground"
            value={level}
            onChange={(event) => onLevelChange(Number(event.target.value))}
          >
            <option value={30}>Combat level 30</option>
            <option value={40}>Combat level 40</option>
          </select>
          <span className="mx-1 h-4 w-px bg-border" />
          <Database className="size-4 text-primary" />
          <span>{data ? data.count.toLocaleString() : '…'} ranked builds</span>
          <span className="mx-1 h-4 w-px bg-border" />
          <span>
            {kits
              ? `${kits.count.toLocaleString()} KO kits`
              : 'Loading KO kits…'}
          </span>
          <span className="mx-1 h-4 w-px bg-border" />
          <span>Priority model · not final simulation</span>
        </div>
      </div>
    </header>
  );
}
