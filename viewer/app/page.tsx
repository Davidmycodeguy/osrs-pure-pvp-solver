'use client';

import { useCallback, useDeferredValue, useMemo, useState } from 'react';

import { BuildDetailPanel } from '@/components/build-detail-panel';
import { BuildsTable } from '@/components/builds-table';
import { FiltersBar } from '@/components/filters-bar';
import { Glossary } from '@/components/glossary';
import {
  type KitColumn,
  columnByKey,
  rowsAsCsv,
  useVisibleColumns,
} from '@/components/kit-columns';
import { KitsTable, type KitSortKey } from '@/components/kits-table';
import { LoadErrorNotice, LoadingSkeleton } from '@/components/loading-states';
import { SiteHeader } from '@/components/site-header';
import { SummaryTiles } from '@/components/summary-tiles';
import { TableFooter } from '@/components/table-footer';
import { useDatasets } from '@/hooks/use-datasets';
import {
  type Dataset,
  type KitDataset,
  kitsByBuild,
  makeIndex,
  numberAt,
} from '@/lib/dataset';
import {
  ALL_KO,
  ALL_WEAPONS,
  PAGE_SIZE,
  type KitFilters,
  type RankMode,
  type SortKey,
  type ViewMode,
  type ViewRow,
  countEnvelopeTwins,
  filterBuilds,
  filterKits,
  firstKitBuildRank,
  listKoWeapons,
  listWeaponTypes,
  rankIndex,
  rankModeOf,
} from '@/lib/filtering';

export default function Home() {
  const [level, setLevel] = useState(40);
  const [query, setQuery] = useState('');
  const [tier, setTier] = useState('All');
  const [weaponType, setWeaponType] = useState(ALL_WEAPONS);
  const [koWeapon, setKoWeapon] = useState(ALL_KO);
  const [seedOnly, setSeedOnly] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>('kits');
  const [sortKey, setSortKey] = useState<SortKey>('rank');
  const [kitSortKey, setKitSortKey] = useState<KitSortKey>('rank');
  const [sortDescending, setSortDescending] = useState(false);
  const [page, setPage] = useState(0);
  const [selectedRank, setSelectedRank] = useState(1);
  const [selectedKit, setSelectedKit] = useState<number | null>(null);
  const [showGlossary, setShowGlossary] = useState(false);
  const [visibleColumns, setVisibleColumns] = useVisibleColumns();
  const [copied, setCopied] = useState('');
  const deferredQuery = useDeferredValue(query.trim().toLowerCase());
  const rankMode = rankModeOf(kitSortKey);

  // Open the panel on the top kit so the two rankings are not confused.
  const selectTopKit = useCallback((loaded: KitDataset, builds: Dataset) => {
    setSelectedKit(0);
    setSelectedRank(firstKitBuildRank(loaded, builds));
  }, []);
  const { data, kits, kitsState, error, loadKits, reset } = useDatasets(
    level,
    selectTopKit,
  );

  const index = useMemo(() => (data ? makeIndex(data.fields) : {}), [data]);
  const kitIndex = useMemo(() => (kits ? makeIndex(kits.fields) : {}), [kits]);
  const kitGroups = useMemo(
    () => (kits ? kitsByBuild(kits, kitIndex) : new Map<number, number[]>()),
    [kits, kitIndex],
  );
  const weaponTypes = useMemo(
    () => (data ? listWeaponTypes(data, index) : []),
    [data, index],
  );
  const koWeapons = useMemo(
    () => (kits ? listKoWeapons(kits, kitIndex) : []),
    [kits, kitIndex],
  );

  const filters = useMemo<KitFilters>(
    () => ({ tier, weaponType, seedOnly, query: deferredQuery, koWeapon }),
    [tier, weaponType, seedOnly, deferredQuery, koWeapon],
  );
  const filteredRows = useMemo<ViewRow[]>(() => {
    if (!data || viewMode === 'kits') return [];
    const grouped = viewMode === 'envelopes';
    return filterBuilds(data, index, filters, grouped, sortKey, sortDescending);
  }, [data, index, filters, viewMode, sortKey, sortDescending]);
  const filteredKits = useMemo<number[]>(() => {
    if (!data || !kits || viewMode !== 'kits') return [];
    const context = { kits, kitIndex, data, buildIndex: index };
    return filterKits(context, filters, kitSortKey, sortDescending);
  }, [
    data,
    kits,
    index,
    kitIndex,
    viewMode,
    filters,
    kitSortKey,
    sortDescending,
  ]);

  const visibleCount =
    viewMode === 'kits' ? filteredKits.length : filteredRows.length;
  const pageCount = Math.max(1, Math.ceil(visibleCount / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageRows = filteredRows.slice(
    safePage * PAGE_SIZE,
    (safePage + 1) * PAGE_SIZE,
  );
  const pageKits = filteredKits.slice(
    safePage * PAGE_SIZE,
    (safePage + 1) * PAGE_SIZE,
  );
  const rankToIndex = useMemo(() => rankIndex(data, index), [data, index]);
  const selectedBuildIndex = rankToIndex.get(selectedRank) ?? 0;
  const selected = data?.rows[selectedBuildIndex] ?? null;
  const selectedEnvelopeCount = useMemo(
    () => (data && selected ? countEnvelopeTwins(data, index, selected) : 0),
    [data, selected, index],
  );

  const buildOptions = kits ? (kitGroups.get(selectedBuildIndex) ?? []) : [];
  const activeKit =
    kits &&
    selectedKit !== null &&
    numberAt(kits.rows[selectedKit], kitIndex, 'build') === selectedBuildIndex
      ? selectedKit
      : (buildOptions[0] ?? null);
  const columns = visibleColumns
    .map(columnByKey)
    .filter((column): column is KitColumn => column !== undefined);

  /** Filter changes always jump back to the first page. */
  function filterSetter<T>(setter: (value: T) => void) {
    return (value: T) => {
      setter(value);
      setPage(0);
    };
  }

  function changeSort(next: SortKey) {
    setPage(0);
    if (sortKey === next) setSortDescending((value) => !value);
    else {
      setSortKey(next);
      setSortDescending(next !== 'rank');
    }
  }

  function changeKitSort(next: KitSortKey) {
    setPage(0);
    if (kitSortKey === next) setSortDescending((value) => !value);
    else {
      setKitSortKey(next);
      const ascending =
        ['rank', 'pressure_rank', 'build_rank'].includes(next) ||
        columnByKey(next)?.kind === 'text';
      setSortDescending(!ascending);
    }
  }

  function changeRankMode(mode: RankMode) {
    setKitSortKey(mode === 'pressure' ? 'pressure_rank' : 'rank');
    setSortDescending(false);
    setPage(0);
  }

  function copyCsv() {
    if (!data || !kits) return;
    const { csv, rows } = rowsAsCsv(columns, filteredKits, {
      kits,
      kitIndex,
      data,
      buildIndex: index,
    });
    navigator.clipboard
      .writeText(csv)
      .then(() => setCopied(`Copied ${rows.toLocaleString()} rows`))
      .catch(() => setCopied('Clipboard blocked by the browser'));
  }

  function selectKit(kitRow: number) {
    if (!kits) return;
    setSelectedKit(kitRow);
    if (data)
      setSelectedRank(
        numberAt(
          data.rows[numberAt(kits.rows[kitRow], kitIndex, 'build')],
          index,
          'rank',
        ),
      );
  }

  function changeView(next: ViewMode) {
    setViewMode(next);
    setPage(0);
    setSortDescending(false);
    if (next === 'kits') {
      setKitSortKey('rank');
      loadKits();
    } else {
      setSortKey('rank');
    }
  }

  function changeLevel(next: number) {
    setLevel(next);
    reset();
    setPage(0);
    setSelectedKit(null);
    setSelectedRank(1);
  }

  return (
    <main className="min-h-screen bg-background text-foreground">
      <SiteHeader
        level={level}
        data={data}
        kits={kits}
        onLevelChange={changeLevel}
      />

      <div className="mx-auto max-w-[1680px] px-4 py-5 sm:px-6 lg:px-8">
        <SummaryTiles level={level} data={data} kits={kits} index={index} />

        {showGlossary ? <Glossary /> : null}

        <section className="grid gap-4 2xl:grid-cols-[minmax(0,1.7fr)_430px]">
          <div className="panel min-w-0 overflow-hidden">
            <FiltersBar
              viewMode={viewMode}
              hasData={data !== null}
              visibleCount={visibleCount}
              query={query}
              onQueryChange={filterSetter(setQuery)}
              weaponType={weaponType}
              weaponTypes={weaponTypes}
              onWeaponTypeChange={filterSetter(setWeaponType)}
              koWeapon={koWeapon}
              koWeapons={koWeapons}
              onKoWeaponChange={filterSetter(setKoWeapon)}
              tier={tier}
              onTierChange={filterSetter(setTier)}
              onViewChange={changeView}
              seedOnly={seedOnly}
              onToggleSeedOnly={() => {
                setSeedOnly((value) => !value);
                setPage(0);
              }}
              showGlossary={showGlossary}
              onToggleGlossary={() => setShowGlossary((value) => !value)}
              rankMode={rankMode}
              onRankModeChange={changeRankMode}
              visibleColumns={visibleColumns}
              onVisibleColumnsChange={setVisibleColumns}
            />

            {error ? (
              <LoadErrorNotice message={error} />
            ) : !data || (viewMode === 'kits' && !kits) ? (
              <LoadingSkeleton viewMode={viewMode} kitsState={kitsState} />
            ) : (
              <>
                {viewMode === 'kits' && kits ? (
                  <KitsTable
                    kits={kits}
                    kitIndex={kitIndex}
                    data={data}
                    buildIndex={index}
                    columns={columns}
                    pageRows={pageKits}
                    selectedKit={activeKit}
                    sortKey={kitSortKey}
                    sortDescending={sortDescending}
                    onSelect={selectKit}
                    onSort={changeKitSort}
                  />
                ) : (
                  <BuildsTable
                    data={data}
                    index={index}
                    kits={kits}
                    kitIndex={kitIndex}
                    kitGroups={kitGroups}
                    rankToIndex={rankToIndex}
                    pageRows={pageRows}
                    selectedRank={selectedRank}
                    onSelect={setSelectedRank}
                    onSort={changeSort}
                  />
                )}
                <TableFooter
                  visibleCount={visibleCount}
                  page={safePage}
                  pageCount={pageCount}
                  onPageChange={setPage}
                  showCopy={viewMode === 'kits' && kits !== null}
                  copied={copied}
                  onCopy={copyCsv}
                />
              </>
            )}
          </div>

          <BuildDetailPanel
            data={data}
            index={index}
            kits={kits}
            kitIndex={kitIndex}
            kitsState={kitsState}
            selected={selected}
            selectedRank={selectedRank}
            activeKit={activeKit}
            buildOptions={buildOptions}
            envelopeCount={selectedEnvelopeCount}
            onSelectKit={selectKit}
            onLoadKits={loadKits}
          />
        </section>
      </div>
    </main>
  );
}
