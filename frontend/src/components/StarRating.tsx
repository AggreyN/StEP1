"use client";
// A 1 to 5 star rating, built as a radio group: Tab reaches it in one stop,
// arrow keys move the choice, and each star is named ("4 stars"). The chosen
// value is also written out as text.
import { useRef, type KeyboardEvent } from "react";

const LABELS = ["", "1 star", "2 stars", "3 stars", "4 stars", "5 stars"];

export function Star({ filled, className = "" }: { filled: boolean; className?: string }) {
  return (
    <svg viewBox="0 0 20 20" aria-hidden className={`shrink-0 ${className}`} fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinejoin="round" d="M10 2.5l2.3 4.8 5.2.7-3.8 3.6.9 5.2L10 14.3l-4.6 2.5.9-5.2L2.5 8l5.2-.7L10 2.5z" />
    </svg>
  );
}

/** Stars for display only, with the number said once for assistive tech. */
export function Stars({ rating, size = "h-4 w-4" }: { rating: number; size?: string }) {
  return (
    <span className="inline-flex items-center gap-0.5 text-accent" role="img" aria-label={`${rating} out of 5 stars`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <Star key={n} filled={n <= rating} className={size} />
      ))}
    </span>
  );
}

export function StarRating({
  value,
  onChange,
  labelledBy,
}: {
  value: number | null;
  onChange: (v: number) => void;
  labelledBy: string;
}) {
  const group = useRef<HTMLDivElement>(null);

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const step = e.key === "ArrowRight" || e.key === "ArrowUp" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowDown" ? -1 : 0;
    let next: number | null = null;
    if (step) next = Math.min(5, Math.max(1, (value ?? (step > 0 ? 0 : 6)) + step));
    if (e.key === "Home") next = 1;
    if (e.key === "End") next = 5;
    if (next === null) return;
    e.preventDefault();
    onChange(next);
    group.current?.querySelector<HTMLElement>(`[data-value="${next}"]`)?.focus();
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <div
        ref={group}
        role="radiogroup"
        aria-labelledby={labelledBy}
        onKeyDown={onKeyDown}
        className="inline-flex items-center gap-1"
        data-testid="star-rating"
      >
        {[1, 2, 3, 4, 5].map((n) => {
          const checked = value === n;
          // Roving focus: the chosen star, or the first one before any choice.
          const tabbable = value === null ? n === 1 : checked;
          return (
            <button
              key={n}
              type="button"
              role="radio"
              aria-checked={checked}
              aria-label={LABELS[n]}
              tabIndex={tabbable ? 0 : -1}
              data-value={n}
              onClick={() => onChange(n)}
              className={`inline-flex h-11 w-11 items-center justify-center rounded-control hover:bg-surface-2 ${
                value !== null && n <= value ? "text-accent" : "text-faint"
              }`}
            >
              <Star filled={value !== null && n <= value} className="h-7 w-7" />
            </button>
          );
        })}
      </div>
      <span className="text-sm text-muted" data-testid="rating-text" aria-live="polite">
        {value ? `${LABELS[value]} out of 5` : "No rating chosen"}
      </span>
    </div>
  );
}
