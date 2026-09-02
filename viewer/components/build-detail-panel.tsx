'use client';

import { Layers3, Swords } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  AccountLevels,
  AuditDetails,
  BonusGrids,
  CombatOutput,
  ModelledGear,
  RankReasons,
  RankingDimensions,
} from '@/components/build-detail-sections';
import { KoSwitchPanel } from '@/components/ko-switch-panel';
import type { KitsState } from '@/hooks/use-datasets';
import {
  type Dataset,
  type FieldIndex,
  type KitDataset,
  type RawRow,
  numberAt,
  percentAt,
  stringAt,
  tierClasses,
} from '@/lib/dataset';

type Props = {
  data: Dataset | null;
  index: FieldIndex;
  kits: KitDataset | null;
  kitIndex: FieldIndex;
  kitsState: KitsState;
  /** The selected build row, or null until the builds have loaded. */
  selected: RawRow | null;
  selectedRank: number;
  /** Kit row shown in the panel, or null when no kit belongs to the selected build. */
  activeKit: number | null;
  /** Every kit that extends the selected build, in kit-rank order. */
  buildOptions: number[];
  /** Account profiles that share the selected build's combat envelope. */
  envelopeCount: number;
  onSelectKit: (kitRow: number) => void;
  onLoadKits: () => void;
};

type HeaderProps = {
  data: Dataset;
  index: FieldIndex;
  kits: KitDataset | null;
  kitIndex: FieldIndex;
  selected: RawRow;
  selectedRank: number;
  activeKit: number | null;
  envelopeCount: number;
};

function DetailHeader({
  data,
  index,
  kits,
  kitIndex,
  selected,
  selectedRank,
  activeKit,
  envelopeCount,
}: HeaderProps) {
  return (
    <div className="border-b border-border bg-[radial-gradient(circle_at_top_right,var(--detail-glow),transparent_54%)] p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Badge
              variant="outline"
              className={tierClasses(
                stringAt(selected, data.strings, index, 'tier'),
              )}
            >
              Tier {stringAt(selected, data.strings, index, 'tier')}
            </Badge>
            {kits && activeKit !== null ? (
              <span className="font-mono text-xs font-semibold text-primary">
                Kit #
                {numberAt(
                  kits.rows[activeKit],
                  kitIndex,
                  'rank',
                ).toLocaleString()}
              </span>
            ) : null}
            <span className="font-mono text-xs text-muted-foreground">
              Build #{selectedRank}
            </span>
            {numberAt(selected, index, 'simulator_seed') === 1 ? (
              <Badge
                variant="outline"
                className="border-emerald-300/25 bg-emerald-300/10 text-emerald-200"
              >
                Simulator seed
              </Badge>
            ) : null}
          </div>
          <h2 className="truncate text-xl font-semibold tracking-tight">
            {stringAt(selected, data.strings, index, 'weapon')}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            with{' '}
            {stringAt(selected, data.strings, index, 'ammo') || 'no ammunition'}
          </p>
        </div>
        <div className="text-right">
          {kits && activeKit !== null ? (
            <>
              <p className="font-mono text-2xl font-semibold text-primary">
                {percentAt(
                  kits.rows[activeKit],
                  kitIndex,
                  'score',
                  kits.scale,
                ).toFixed(3)}
              </p>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                kit score
              </p>
              <p className="mt-1 font-mono text-xs text-muted-foreground">
                build {percentAt(selected, index, 'score').toFixed(3)}
              </p>
            </>
          ) : (
            <>
              <p className="font-mono text-2xl font-semibold text-primary">
                {percentAt(selected, index, 'score').toFixed(3)}
              </p>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                build score
              </p>
            </>
          )}
        </div>
      </div>
      {envelopeCount > 1 ? (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-primary/15 bg-primary/7 px-3 py-2 text-xs text-primary">
          <Layers3 className="size-4" />
          {envelopeCount} account profiles share this exact combat envelope
        </div>
      ) : null}
    </div>
  );
}

function KoKitsPrompt({
  kitsState,
  onLoadKits,
}: {
  kitsState: KitsState;
  onLoadKits: () => void;
}) {
  return (
    <section className="rounded-lg border border-primary/20 bg-primary/6 p-4">
      <div className="flex items-center gap-2 text-xs font-medium text-primary">
        <Swords className="size-4" /> KO switch kits
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        {kitsState === 'error'
          ? 'KO kit data could not load.'
          : kitsState === 'loading'
            ? 'Loading the KO kit data (large, one-time)…'
            : 'Load the KO kit data to see every switch weapon this build can carry, with stack odds, food cost and kit rank.'}
      </p>
      {kitsState === 'idle' ? (
        <Button size="sm" className="mt-3" onClick={onLoadKits}>
          <Swords /> Load KO kits
        </Button>
      ) : null}
    </section>
  );
}

/** The right-hand panel: selected build header, its KO kit, and every modelled stat. */
export function BuildDetailPanel({
  data,
  index,
  kits,
  kitIndex,
  kitsState,
  selected,
  selectedRank,
  activeKit,
  buildOptions,
  envelopeCount,
  onSelectKit,
  onLoadKits,
}: Props) {
  return (
    <aside className="panel h-fit overflow-hidden 2xl:sticky 2xl:top-[76px]">
      {!data || !selected ? (
        <div className="h-[680px] animate-pulse bg-muted/35" />
      ) : (
        <>
          <DetailHeader
            data={data}
            index={index}
            kits={kits}
            kitIndex={kitIndex}
            selected={selected}
            selectedRank={selectedRank}
            activeKit={activeKit}
            envelopeCount={envelopeCount}
          />

          <div className="max-h-[calc(100vh-170px)] space-y-6 overflow-y-auto p-5">
            {kits && activeKit !== null ? (
              <KoSwitchPanel
                kits={kits}
                kitIndex={kitIndex}
                kit={kits.rows[activeKit]}
                build={selected}
                buildIndex={index}
                options={buildOptions}
                selectedKit={activeKit}
                onSelectKit={onSelectKit}
              />
            ) : (
              <KoKitsPrompt kitsState={kitsState} onLoadKits={onLoadKits} />
            )}
            <AccountLevels selected={selected} index={index} />
            <ModelledGear selected={selected} data={data} index={index} />
            <CombatOutput selected={selected} index={index} />
            <BonusGrids selected={selected} index={index} />
            <RankingDimensions selected={selected} index={index} />
            <RankReasons selected={selected} data={data} index={index} />
            <AuditDetails selected={selected} data={data} index={index} />
          </div>
        </>
      )}
    </aside>
  );
}
