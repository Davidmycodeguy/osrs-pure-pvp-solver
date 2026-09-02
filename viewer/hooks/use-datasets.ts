import { useCallback, useEffect, useState } from 'react';

import type { Dataset, KitDataset } from '@/lib/dataset';

export type KitsState = 'idle' | 'loading' | 'error';

/**
 * Datasets live under public/data and are served from the same origin as the page, by the dev
 * server and by `vinext start` alike. The gzipped copies next to them are release assets for
 * scripts/fetch_data.py; the page reads the plain JSON.
 */
async function fetchDataset<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, { signal });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return (await response.json()) as T;
}

/**
 * Loads the builds for a combat level, then its KO kits. `onKitsLoaded` runs once the kits
 * arrive (with at least one row) so the page can point its selection at the top kit; pass a
 * stable callback, since it is an effect dependency.
 */
export function useDatasets(
  level: number,
  onKitsLoaded: (kits: KitDataset, builds: Dataset) => void,
) {
  const [data, setData] = useState<Dataset | null>(null);
  const [error, setError] = useState('');
  const [kits, setKits] = useState<KitDataset | null>(null);
  const [kitsState, setKitsState] = useState<KitsState>('loading');

  useEffect(() => {
    const controller = new AbortController();
    let buildsLoaded = false;
    let builds: Dataset | null = null;
    fetchDataset<Dataset>(`/data/builds-${level}.json`, controller.signal)
      .then((loaded) => {
        setData(loaded);
        builds = loaded;
        buildsLoaded = true;
        // The kit ranking is the headline result; fetch it right after the builds.
        return fetchDataset<KitDataset>(
          `/data/kits-${level}.json`,
          controller.signal,
        );
      })
      .then((loaded) => {
        setKits(loaded);
        setKitsState('idle');
        if (loaded.rows.length > 0 && builds) onKitsLoaded(loaded, builds);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === 'AbortError')
          return;
        setKitsState('error');
        if (!buildsLoaded)
          setError(
            reason instanceof Error
              ? reason.message
              : 'Could not load build data',
          );
      });
    return () => controller.abort();
  }, [level, onKitsLoaded]);

  /** Retry the kit download after a failure (the builds stay loaded). */
  const loadKits = useCallback(() => {
    if (kits || kitsState === 'loading') return;
    setKitsState('loading');
    fetchDataset<KitDataset>(`/data/kits-${level}.json`)
      .then((loaded) => {
        setKits(loaded);
        setKitsState('idle');
        if (loaded.rows.length > 0 && data) onKitsLoaded(loaded, data);
      })
      .catch(() => setKitsState('error'));
  }, [kits, kitsState, level, data, onKitsLoaded]);

  /** Clear everything before switching level so stale rows never show under the new header. */
  const reset = useCallback(() => {
    setData(null);
    setKits(null);
    setError('');
    setKitsState('loading');
  }, []);

  return { data, kits, kitsState, error, loadKits, reset };
}
