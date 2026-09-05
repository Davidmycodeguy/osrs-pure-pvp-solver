'use client';

import type { ReactNode } from 'react';
import {
  BarChart3,
  BookOpen,
  Flame,
  Layers3,
  Search,
  SlidersHorizontal,
  Swords,
  Target,
  Users,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ColumnPicker } from '@/components/kit-columns';
import {
  ALL_KO,
  ALL_WEAPONS,
  NO_SWITCH,
  type RankMode,
  type ViewMode,
  tierOrder,
} from '@/lib/filtering';

const viewButtons: Array<[ViewMode, ReactNode, string]> = [
  ['envelopes', <Layers3 key="e" />, 'Unique envelopes'],
  ['profiles', <Users key="p" />, 'All profiles'],
  ['kits', <Swords key="k" />, 'KO kits'],
];

type Props = {
  viewMode: ViewMode;
  /** False until the build dataset has arrived. */
  hasData: boolean;
  visibleCount: number;
  query: string;
  onQueryChange: (value: string) => void;
  weaponType: string;
  weaponTypes: string[];
  onWeaponTypeChange: (value: string) => void;
  koWeapon: string;
  koWeapons: string[];
  onKoWeaponChange: (value: string) => void;
  tier: string;
  onTierChange: (value: string) => void;
  onViewChange: (mode: ViewMode) => void;
  seedOnly: boolean;
  onToggleSeedOnly: () => void;
  showGlossary: boolean;
  onToggleGlossary: () => void;
  showStatFilters: boolean;
  onToggleStatFilters: () => void;
  /** How many stats currently narrow the table, shown on the toggle. */
  activeStats: number;
  rankMode: RankMode;
  onRankModeChange: (mode: RankMode) => void;
  visibleColumns: string[];
  onVisibleColumnsChange: (next: string[]) => void;
};

/** Title, search, selects, tier and view toggles, and the kit "Rank by" row above the table. */
export function FiltersBar({
  viewMode,
  hasData,
  visibleCount,
  query,
  onQueryChange,
  weaponType,
  weaponTypes,
  onWeaponTypeChange,
  koWeapon,
  koWeapons,
  onKoWeaponChange,
  tier,
  onTierChange,
  onViewChange,
  seedOnly,
  onToggleSeedOnly,
  showGlossary,
  onToggleGlossary,
  showStatFilters,
  onToggleStatFilters,
  activeStats,
  rankMode,
  onRankModeChange,
  visibleColumns,
  onVisibleColumnsChange,
}: Props) {
  return (
    <div className="border-b border-border p-4">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <h2 className="font-semibold">
            {viewMode === 'kits' ? 'Ranked KO kits' : 'Ranked builds'}
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {hasData
              ? `${visibleCount.toLocaleString()} visible results`
              : 'Loading every ranked build…'}
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative block min-w-0 flex-1 xl:w-72">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label="Search builds"
              className="h-9 border-border/80 bg-background/70 pl-9"
              placeholder="Search gear, weapon, ID or #rank…"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
            />
          </div>
          <select
            aria-label="Weapon type"
            className="h-9 rounded-lg border border-border bg-background px-3 text-sm text-foreground"
            value={weaponType}
            onChange={(event) => onWeaponTypeChange(event.target.value)}
          >
            <option>{ALL_WEAPONS}</option>
            {weaponTypes.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
          {viewMode === 'kits' ? (
            <select
              aria-label="KO weapon"
              className="h-9 rounded-lg border border-border bg-background px-3 text-sm text-foreground"
              value={koWeapon}
              onChange={(event) => onKoWeaponChange(event.target.value)}
            >
              <option>{ALL_KO}</option>
              <option>{NO_SWITCH}</option>
              {koWeapons.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          ) : null}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1.5">
          {tierOrder.map((value) => (
            <Button
              key={value}
              size="sm"
              variant={tier === value ? 'default' : 'outline'}
              onClick={() => onTierChange(value)}
            >
              {value === 'All' ? 'All tiers' : `Tier ${value}`}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {viewButtons.map(([mode, icon, label]) => (
            <Button
              key={mode}
              size="sm"
              variant={viewMode === mode ? 'secondary' : 'outline'}
              onClick={() => onViewChange(mode)}
            >
              {icon} {label}
            </Button>
          ))}
          <Button
            size="sm"
            variant={seedOnly ? 'default' : 'outline'}
            onClick={onToggleSeedOnly}
          >
            <Target /> Simulator 32
          </Button>
          <Button
            size="sm"
            variant={showStatFilters || activeStats > 0 ? 'default' : 'outline'}
            onClick={onToggleStatFilters}
          >
            <SlidersHorizontal /> Stat filters
            {activeStats > 0 ? ` (${activeStats})` : ''}
          </Button>
          <Button
            size="sm"
            variant={showGlossary ? 'default' : 'outline'}
            onClick={onToggleGlossary}
          >
            <BookOpen /> What the numbers mean
          </Button>
        </div>
      </div>

      {viewMode === 'kits' ? (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted-foreground">Rank by</span>
          <Button
            size="sm"
            variant={rankMode === 'attrition' ? 'secondary' : 'outline'}
            onClick={() => onRankModeChange('attrition')}
          >
            <BarChart3 /> Attrition (kit score)
          </Button>
          <Button
            size="sm"
            variant={rankMode === 'pressure' ? 'secondary' : 'outline'}
            onClick={() => onRankModeChange('pressure')}
          >
            <Flame /> Kill pressure
          </Button>
          <span className="text-muted-foreground">
            {rankMode === 'pressure'
              ? 'Sorted by chance the burst beats one fish, then bite, then race margin. Raw odds, not percentiles.'
              : 'Sorted by the mean of six category percentiles. Rewards the long trade; blind to finishing.'}
          </span>
          <span className="ml-auto">
            <ColumnPicker
              visible={visibleColumns}
              onChange={onVisibleColumnsChange}
            />
          </span>
        </div>
      ) : null}
    </div>
  );
}
