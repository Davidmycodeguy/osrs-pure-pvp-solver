'use client';

import { useCallback, useDeferredValue, useMemo, useState } from 'react';

import { BuildDetailPanel } from '@/components/build-detail-panel';
import { BuildsTable } from '@/components/builds-table';
import { ComparePanel } from '@/components/compare-panel';
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
import { StatFiltersPanel } from '@/components/stat-filters-panel';
import { SummaryTiles } from '@/components/summary-tiles';
import { TableFooter } from '@/components/table-footer';
import { useDatasets } from '@/hooks/use-datasets';
import {
  type Dataset,
  type KitDataset,
  SCALE,
  kitsByBuild,
  makeIndex,
  numberAt,
} from '@/lib/dataset';
import { buildCompareView, kitCompareView, togglePinned } from '@/lib/compare';
import {
  type StatEdge,
  type StatInputs,
  activeStatCount,
  clearStatInputs,
  setStatInput,
  toStatRanges,
} from '@/lib/stat-filters';
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
  const [statInputs, setStatInputs] = useState<StatInputs>({});
  const [showStatFilters, setShowStatFilters] = useState(false);
  const [pinnedKits, setPinnedKits] = useState<number[]>([]);
  const [pinnedBuilds, setPinnedBuilds] = useState<number[]>([]);
  const [differencesOnly, setDifferencesOnly] = useState(false);
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

  // Kit percentages are stored at the kit dataset's own scale; before it lands only build stats
  // can be filtered, and those always use SCALE.
  const kitScale = kits?.scale ?? SCALE;
  const statRanges = useMemo(
    () => toStatRanges(statInputs, kitScale),
    [statInputs, kitScale],
  );
  const activeStats = activeStatCount(statRanges);
  const filters = useMemo<KitFilters>(
    () => ({
      tier,
      weaponType,
      seedOnly,
      query: deferredQuery,
      koWeapon,
      stats: statRanges,
    }),
    [tier, weaponType, seedOnly, deferredQuery, koWeapon, statRanges],
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
  const columns = useMemo(
    () =>
      visibleColumns
        .map(columnByKey)
        .filter((column): column is KitColumn => column !== undefined),
    [visibleColumns],
  );

  const pinned = viewMode === 'kits' ? pinnedKits : pinnedBuilds;
  const compareView = useMemo(() => {
    if (!data || pinned.length === 0) return null;
    if (viewMode === 'kits')
      return kits
        ? kitCompareView(pinned, columns, {
            kits,
            kitIndex,
            data,
            buildIndex: index,
          })
        : null;
    return buildCompareView(pinned, columns, data, index, rankToIndex);
  }, [data, kits, kitIndex, index, rankToIndex, pinned, viewMode, columns]);

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

  function changeStat(key: string, edge: StatEdge, text: string) {
    setStatInputs((current) => setStatInput(current, key, edge, text));
    setPage(0);
  }

  function clearStats() {
    setStatInputs(clearStatInputs());
    setPage(0);
  }

  function togglePinnedRow(id: number) {
    if (viewMode === 'kits')
      setPinnedKits((current) => togglePinned(current, id));
    else setPinnedBuilds((current) => togglePinned(current, id));
  }

  function clearPins() {
    if (viewMode === 'kits') setPinnedKits([]);
    else setPinnedBuilds([]);
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
    // Pins are row ids within one level's dataset, so they mean nothing after a switch.
    setPinnedKits([]);
    setPinnedBuilds([]);
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
              showStatFilters={showStatFilters}
              onToggleStatFilters={() => setShowStatFilters((value) => !value)}
              activeStats={activeStats}
              rankMode={rankMode}
              onRankModeChange={changeRankMode}
              visibleColumns={visibleColumns}
              onVisibleColumnsChange={setVisibleColumns}
            />

            {showStatFilters ? (
              <div className="px-4 pb-4">
                <StatFiltersPanel
                  viewMode={viewMode}
                  inputs={statInputs}
                  activeCount={activeStats}
                  onChange={changeStat}
                  onClear={clearStats}
                />
              </div>
            ) : null}

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
                    pinned={pinnedKits}
                    onSelect={selectKit}
                    onSort={changeKitSort}
                    onTogglePin={togglePinnedRow}
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
                    pinned={pinnedBuilds}
                    onSelect={setSelectedRank}
                    onSort={changeSort}
                    onTogglePin={togglePinnedRow}
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

        {compareView && compareView.entries.length > 0 ? (
          <ComparePanel
            view={compareView}
            differencesOnly={differencesOnly}
            onToggleDifferencesOnly={() =>
              setDifferencesOnly((value) => !value)
            }
            onUnpin={togglePinnedRow}
            onClear={clearPins}
          />
        ) : null}
      </div>
    </main>
  );
}
