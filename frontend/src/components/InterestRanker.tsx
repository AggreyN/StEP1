"use client";
// Pick 3–5 fields of interest and rank them. Rank drives the match score, so
// the number is always visible and reordering is explicit (up/down buttons —
// keyboard and touch friendly, no drag library).
import { useState } from "react";
import { ROLE_KEYS, roleLabel } from "@/lib/roles";
import { DownIcon, UpIcon, XIcon } from "./icons";

export const MIN_INTERESTS = 3;
export const MAX_INTERESTS = 5;

export function interestError(n: number): string | null {
  if (n < MIN_INTERESTS) return `Pick at least ${MIN_INTERESTS}. ${MIN_INTERESTS - n} more to go.`;
  if (n > MAX_INTERESTS) return `Pick at most ${MAX_INTERESTS}. Remove ${n - MAX_INTERESTS}.`;
  return null;
}

export function InterestRanker({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  // Said aloud by screen readers after each change (the list is visual).
  const [announcement, setAnnouncement] = useState("");

  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= value.length) return; // already first or last
    const next = [...value];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
    setAnnouncement(`${roleLabel(value[i])} is now number ${j + 1} of ${value.length}.`);
  };
  const remove = (key: string) => {
    onChange(value.filter((k) => k !== key));
    setAnnouncement(`${roleLabel(key)} removed.`);
  };
  const add = (key: string) => {
    onChange([...value, key]);
    setAnnouncement(`${roleLabel(key)} added as number ${value.length + 1}.`);
  };
  const available = ROLE_KEYS.filter((k) => !value.includes(k));
  const err = interestError(value.length);

  return (
    <div>
      <ol aria-label="Your ranked fields" className="space-y-2">
        {value.map((key, i) => (
          <li
            key={key}
            data-testid="ranked-interest"
            className="flex items-center gap-2 rounded-control border border-line bg-surface py-1.5 pl-2 pr-1 sm:gap-3"
          >
            <span
              aria-label={`Rank ${i + 1}`}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-chip bg-surface-2 font-mono text-sm font-semibold"
            >
              {i + 1}
            </span>
            <span className="min-w-0 flex-1 break-words text-[15px] font-medium leading-snug">{roleLabel(key)}</span>
            <button
              type="button"
              onClick={() => move(i, -1)}
              // aria-disabled, not disabled: a disabled button drops focus,
              // which would strand a keyboard user who just moved an item to
              // the top.
              aria-disabled={i === 0}
              aria-label={`Move ${roleLabel(key)} up`}
              className="inline-flex h-10 w-9 shrink-0 items-center justify-center rounded-chip text-muted hover:bg-surface-2 hover:text-fg aria-disabled:cursor-not-allowed aria-disabled:opacity-30 aria-disabled:hover:bg-transparent"
            >
              <UpIcon />
            </button>
            <button
              type="button"
              onClick={() => move(i, 1)}
              aria-disabled={i === value.length - 1}
              aria-label={`Move ${roleLabel(key)} down`}
              className="inline-flex h-10 w-9 shrink-0 items-center justify-center rounded-chip text-muted hover:bg-surface-2 hover:text-fg aria-disabled:cursor-not-allowed aria-disabled:opacity-30 aria-disabled:hover:bg-transparent"
            >
              <DownIcon />
            </button>
            <button
              type="button"
              onClick={() => remove(key)}
              aria-label={`Remove ${roleLabel(key)}`}
              className="inline-flex h-10 w-9 shrink-0 items-center justify-center rounded-chip text-muted hover:bg-surface-2 hover:text-fg"
            >
              <XIcon />
            </button>
          </li>
        ))}
        {value.length === 0 && (
          <li className="rounded-control border border-dashed border-line-strong px-3 py-4 text-sm text-muted">
            Nothing picked yet. Choose fields below. The first one you pick is #1.
          </li>
        )}
      </ol>

      <p className="sr-only" role="status" aria-live="polite" data-testid="rank-announcement">
        {announcement}
      </p>

      <p
        data-testid="interest-status"
        className={`mt-2 text-sm ${err ? (value.length > MAX_INTERESTS ? "text-danger" : "text-muted") : "text-positive"}`}
        aria-live="polite"
      >
        {err ?? `${value.length} picked. Reorder so your top choice is #1.`}
      </p>

      {available.length > 0 && (
        <div className="mt-4">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-faint">Add a field</p>
          <div className="flex flex-wrap gap-2">
            {available.map((key) => (
              <button
                type="button"
                key={key}
                onClick={() => add(key)}
                className="h-9 rounded-control border border-line-strong bg-surface px-3 text-sm text-fg hover:border-accent hover:text-accent-text"
              >
                + {roleLabel(key)}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
