'use client';

import { Pin, PinOff } from 'lucide-react';

type Props = {
  pinned: boolean;
  /** Names the row in the button's accessible label. */
  label: string;
  /** False when the comparison is full and this row is not in it. */
  enabled?: boolean;
  onToggle: () => void;
};

/** The per-row pin toggle. Stops the click short of the row so pinning never changes selection. */
export function PinButton({ pinned, label, enabled = true, onToggle }: Props) {
  const disabled = !pinned && !enabled;
  return (
    <button
      type="button"
      aria-pressed={pinned}
      disabled={disabled}
      title={
        disabled
          ? 'Unpin something first'
          : pinned
            ? `Unpin ${label}`
            : `Pin ${label} to compare`
      }
      aria-label={pinned ? `Unpin ${label}` : `Pin ${label} to compare`}
      className={`rounded p-1 transition-colors ${
        pinned
          ? 'text-primary'
          : disabled
            ? 'cursor-not-allowed text-muted-foreground/35'
            : 'text-muted-foreground/60 hover:text-foreground'
      }`}
      onClick={(event) => {
        event.stopPropagation();
        onToggle();
      }}
    >
      {pinned ? <PinOff className="size-3.5" /> : <Pin className="size-3.5" />}
    </button>
  );
}
