'use client';

import type { KitsState } from '@/hooks/use-datasets';
import type { ViewMode } from '@/lib/filtering';

/** Shown in place of the table when the build dataset itself failed to load. */
export function LoadErrorNotice({ message }: { message: string }) {
  return (
    <div className="grid min-h-[420px] place-items-center p-8 text-center">
      <div>
        <p className="font-semibold text-destructive">
          Build data could not load
        </p>
        <p className="mt-2 text-sm text-muted-foreground">{message}</p>
      </div>
    </div>
  );
}

/** Row placeholders while the builds (or, in the kits view, the kits) download. */
export function LoadingSkeleton({
  viewMode,
  kitsState,
}: {
  viewMode: ViewMode;
  kitsState: KitsState;
}) {
  return (
    <div className="space-y-2 p-4" aria-label="Loading builds">
      {viewMode === 'kits' ? (
        <p className="px-1 pb-2 text-xs text-muted-foreground">
          {kitsState === 'error'
            ? 'KO kit data could not load.'
            : 'Loading the KO kit data (large, one-time)…'}
        </p>
      ) : null}
      {Array.from({ length: 10 }, (_, indexValue) => (
        <div
          key={indexValue}
          className="h-16 animate-pulse rounded-lg bg-muted/55"
        />
      ))}
    </div>
  );
}
