'use client';

import { ChevronLeft, ChevronRight, Copy } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { COPY_CAP } from '@/components/kit-columns';
import { PAGE_SIZE } from '@/lib/filtering';

type Props = {
  visibleCount: number;
  /** Zero-based page already clamped to the page count. */
  page: number;
  pageCount: number;
  onPageChange: (page: number) => void;
  /** The CSV button only applies to the kits view. */
  showCopy: boolean;
  copied: string;
  onCopy: () => void;
};

/** Result range, the CSV export and the pager under either table. */
export function TableFooter({
  visibleCount,
  page,
  pageCount,
  onPageChange,
  showCopy,
  copied,
  onCopy,
}: Props) {
  return (
    <div className="flex flex-col gap-3 border-t border-border px-4 py-3 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
      <span>
        {visibleCount === 0
          ? 'Nothing matches these filters'
          : `Showing ${(page * PAGE_SIZE + 1).toLocaleString()}–${Math.min((page + 1) * PAGE_SIZE, visibleCount).toLocaleString()} of ${visibleCount.toLocaleString()}`}
      </span>
      <div className="flex items-center gap-2">
        {showCopy ? (
          <>
            <Button
              size="sm"
              variant="outline"
              title={`Copies the filtered, sorted kits with the visible columns (first ${COPY_CAP.toLocaleString()} rows)`}
              onClick={onCopy}
            >
              <Copy /> Copy rows as CSV
            </Button>
            {copied ? <span className="text-emerald-300">{copied}</span> : null}
          </>
        ) : null}
        <Button
          size="sm"
          variant="outline"
          disabled={page === 0}
          onClick={() => onPageChange(page - 1)}
        >
          <ChevronLeft /> Previous
        </Button>
        <span className="min-w-24 text-center font-mono">
          {page + 1} / {pageCount}
        </span>
        <Button
          size="sm"
          variant="outline"
          disabled={page + 1 >= pageCount}
          onClick={() => onPageChange(page + 1)}
        >
          Next <ChevronRight />
        </Button>
      </div>
    </div>
  );
}
