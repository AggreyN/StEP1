"use client";
// Two-way switch for the feed order. A segmented control rather than a
// dropdown: both options stay visible and it is one tap on a phone.
import { useRef, type KeyboardEvent } from "react";
import { SORT_OPTIONS } from "@/lib/filters";
import type { FeedSort } from "@/lib/types";

export function SortControl({ value, onChange }: { value: FeedSort; onChange: (s: FeedSort) => void }) {
  const group = useRef<HTMLDivElement>(null);

  // Arrow keys move the choice, as they do in a native radio group; Tab
  // enters and leaves the group in one stop.
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const at = SORT_OPTIONS.findIndex((o) => o.value === value);
    const next = SORT_OPTIONS[(at + step + SORT_OPTIONS.length) % SORT_OPTIONS.length];
    onChange(next.value);
    group.current?.querySelector<HTMLElement>(`[data-value="${next.value}"]`)?.focus();
  }

  return (
    <div
      ref={group}
      role="radiogroup"
      aria-label="Sort"
      data-testid="sort-control"
      onKeyDown={onKeyDown}
      className="inline-flex shrink-0 rounded-control border border-line-strong bg-surface-2 p-0.5"
    >
      {SORT_OPTIONS.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            tabIndex={on ? 0 : -1}
            data-value={o.value}
            onClick={() => onChange(o.value)}
            className={`h-8 whitespace-nowrap rounded-chip px-2 text-[13px] sm:px-3 sm:text-sm ${
              on
                ? "border border-line-strong bg-surface font-medium text-fg"
                : "border border-transparent text-muted hover:text-fg"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
