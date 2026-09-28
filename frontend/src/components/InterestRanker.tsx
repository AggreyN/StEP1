"use client";
// Pick 3–5 fields of interest and rank them. Rank drives the match score, so
// the number is always visible and reordering is explicit (up/down buttons —
// keyboard and touch friendly, no drag library).
import { ROLE_KEYS, roleLabel } from "@/lib/roles";
import { DownIcon, UpIcon, XIcon } from "./icons";

export const MIN_INTERESTS = 3;
export const MAX_INTERESTS = 5;

export function interestError(n: number): string | null {
  if (n < MIN_INTERESTS) return `Pick at least ${MIN_INTERESTS} — ${MIN_INTERESTS - n} more to go.`;
  if (n > MAX_INTERESTS) return `Pick at most ${MAX_INTERESTS} — remove ${n - MAX_INTERESTS}.`;
  return null;
}

export function InterestRanker({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const move = (i: number, d: -1 | 1) => {
    const next = [...value];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    onChange(next);
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
            className="flex items-center gap-3 rounded-lg border border-line bg-surface py-1.5 pl-2 pr-1"
          >
            <span
              aria-label={`Rank ${i + 1}`}
              className="tnum flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-surface-2 text-sm font-semibold"
            >
              {i + 1}
            </span>
            <span className="min-w-0 flex-1 truncate text-[15px] font-medium">{roleLabel(key)}</span>
            <button
              type="button"
              onClick={() => move(i, -1)}
              disabled={i === 0}
              aria-label={`Move ${roleLabel(key)} up`}
              className="inline-flex h-10 w-10 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-30"
            >
              <UpIcon />
            </button>
            <button
              type="button"
              onClick={() => move(i, 1)}
              disabled={i === value.length - 1}
              aria-label={`Move ${roleLabel(key)} down`}
              className="inline-flex h-10 w-10 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-30"
            >
              <DownIcon />
            </button>
            <button
              type="button"
              onClick={() => onChange(value.filter((k) => k !== key))}
              aria-label={`Remove ${roleLabel(key)}`}
              className="inline-flex h-10 w-10 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg"
            >
              <XIcon />
            </button>
          </li>
        ))}
        {value.length === 0 && (
          <li className="rounded-lg border border-dashed border-line-strong px-3 py-4 text-sm text-muted">
            Nothing picked yet. Tap fields below — the first one you pick is #1.
          </li>
        )}
      </ol>

      <p
        data-testid="interest-status"
        className={`mt-2 text-sm ${err ? (value.length > MAX_INTERESTS ? "text-danger" : "text-muted") : "text-positive"}`}
        aria-live="polite"
      >
        {err ?? `${value.length} picked — reorder so your top choice is #1.`}
      </p>

      {available.length > 0 && (
        <div className="mt-4">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-faint">Add a field</p>
          <div className="flex flex-wrap gap-2">
            {available.map((key) => (
              <button
                type="button"
                key={key}
                onClick={() => onChange([...value, key])}
                className="h-9 rounded-full border border-line-strong bg-surface px-3 text-sm text-fg hover:border-accent hover:text-accent-text"
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
