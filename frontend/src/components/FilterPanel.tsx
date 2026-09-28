"use client";
// Dashboard filters. The URL is the source of truth: every change calls
// onChange with the full filter set and the page writes it to the query string.
import { useEffect, useState } from "react";
import { EMPTY_FILTERS, activeFilterKeys } from "@/lib/filters";
import { TERMS } from "@/lib/labels";
import { ROLE_KEYS, roleLabel } from "@/lib/roles";
import type { FeedFilters } from "@/lib/types";
import { CheckIcon } from "./icons";

const SCORE_STEPS = [50, 60, 70, 80, 90];

const field =
  "h-10 w-full rounded-lg border border-line-strong bg-surface px-3 text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none";

export function FilterPanel({ value, onChange }: { value: FeedFilters; onChange: (f: FeedFilters) => void }) {
  // Location is typed; debounce so we don't rewrite the URL per keystroke.
  // When the URL changes underneath us (back button, "Remove location filter"),
  // adopt it — adjusted during render, per React's "derived state" guidance.
  const [loc, setLoc] = useState(value.location);
  const [seen, setSeen] = useState(value.location);
  if (seen !== value.location) {
    setSeen(value.location);
    if (loc.trim() !== value.location) setLoc(value.location);
  }
  useEffect(() => {
    if (loc.trim() === value.location) return;
    const t = setTimeout(() => onChange({ ...value, location: loc.trim() }), 350);
    return () => clearTimeout(t);
  }, [loc, value, onChange]);

  const active = activeFilterKeys(value).length;

  return (
    <div className="space-y-5 text-sm">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-faint">Filters</h2>
        {active > 0 && (
          <button
            type="button"
            onClick={() => onChange(EMPTY_FILTERS)}
            className="text-sm font-medium text-accent-text underline-offset-2 hover:underline"
          >
            Clear all
          </button>
        )}
      </div>

      <fieldset>
        <legend className="mb-2 font-medium">Role</legend>
        <ul className="space-y-0.5">
          {ROLE_KEYS.map((k) => {
            const on = value.roles.includes(k);
            return (
              <li key={k}>
                <label className="flex min-h-9 cursor-pointer items-center gap-2.5 rounded-md px-1.5 py-1 hover:bg-surface-2">
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() =>
                      onChange({ ...value, roles: on ? value.roles.filter((r) => r !== k) : [...value.roles, k] })
                    }
                    className="h-4 w-4 accent-[var(--accent)]"
                  />
                  <span className={on ? "font-medium" : "text-muted"}>{roleLabel(k)}</span>
                </label>
              </li>
            );
          })}
        </ul>
      </fieldset>

      <label className="block">
        <span className="mb-1.5 block font-medium">Location</span>
        <input
          className={field}
          value={loc}
          onChange={(e) => setLoc(e.target.value)}
          placeholder="City, state, or “Remote”"
          aria-label="Location"
        />
      </label>

      <label className="block">
        <span className="mb-1.5 block font-medium">Term</span>
        <select className={field} value={value.term} onChange={(e) => onChange({ ...value, term: e.target.value })} aria-label="Term">
          <option value="">Any term</option>
          {TERMS.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
      </label>

      <label className="block">
        <span className="mb-1.5 block font-medium">Minimum score</span>
        <select
          className={`${field} tnum`}
          value={value.min_score ?? ""}
          onChange={(e) => onChange({ ...value, min_score: e.target.value ? Number(e.target.value) : null })}
          aria-label="Minimum score"
        >
          <option value="">Any score</option>
          {SCORE_STEPS.map((s) => (
            <option key={s} value={s}>
              {s}+
            </option>
          ))}
        </select>
      </label>

      <button
        type="button"
        role="switch"
        aria-checked={value.remote}
        onClick={() => onChange({ ...value, remote: !value.remote })}
        className="flex min-h-10 w-full items-center justify-between rounded-lg border border-line-strong px-3 text-left"
      >
        <span className="font-medium">Remote only</span>
        <span
          className={`inline-flex h-5 w-5 items-center justify-center rounded-md border ${
            value.remote ? "border-accent bg-accent text-accent-fg" : "border-line-strong"
          }`}
        >
          {value.remote && <CheckIcon />}
        </span>
      </button>
    </div>
  );
}
