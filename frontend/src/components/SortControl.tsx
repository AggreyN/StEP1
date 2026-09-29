"use client";
// Two-way switch for the feed order. A segmented control rather than a
// dropdown: both options stay visible and it is one tap on a phone.
import { SORT_OPTIONS } from "@/lib/filters";
import type { FeedSort } from "@/lib/types";

export function SortControl({ value, onChange }: { value: FeedSort; onChange: (s: FeedSort) => void }) {
  return (
    <div
      role="radiogroup"
      aria-label="Sort"
      data-testid="sort-control"
      className="inline-flex shrink-0 rounded-lg bg-surface-2 p-0.5"
    >
      {SORT_OPTIONS.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.value)}
            className={`h-8 whitespace-nowrap rounded-md px-2.5 text-[13px] sm:px-3 sm:text-sm ${
              on ? "bg-surface font-medium text-fg shadow-sm" : "text-muted hover:text-fg"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
