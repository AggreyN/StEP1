// Display formatting helpers — no business logic.
import type { Salary } from "./types";

export function daysAgo(iso: string, now = Date.now()): number {
  return Math.max(0, Math.floor((now - new Date(iso).getTime()) / 86_400_000));
}

export function postedAge(iso: string): string {
  const d = daysAgo(iso);
  if (d === 0) return "today";
  if (d === 1) return "yesterday";
  if (d < 14) return `${d}d ago`;
  if (d < 60) return `${Math.floor(d / 7)}w ago`;
  return `${Math.floor(d / 30)}mo ago`;
}

export function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function longDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function formatSalary(s: Salary | null): string | null {
  if (!s || (s.min == null && s.max == null)) return null;
  const unit = s.unit === "hour" ? "/hr" : s.unit === "year" ? "/yr" : s.unit === "month" ? "/mo" : ` ${s.unit}`;
  const money = (n: number) =>
    s.unit === "hour" ? `$${n}` : `$${n >= 1000 ? Math.round(n / 1000) + "k" : n}`;
  if (s.min != null && s.max != null && s.min !== s.max) return `${money(s.min)}–${money(s.max)}${unit}`;
  return `${money((s.min ?? s.max) as number)}${unit}`;
}

/** Local YYYY-MM-DD for <input type="date">. */
export function todayInput(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Convert a date input value to an ISO timestamp. Today (or blank) returns
 *  undefined so the API stamps the real current time and same-day events keep
 *  their order; a past date becomes local noon (so it can't slip to the
 *  previous day in UTC). */
export function dateInputToIso(v: string): string | undefined {
  if (!v || v === todayInput()) return undefined;
  const [y, m, d] = v.split("-").map(Number);
  return new Date(y, m - 1, d, 12).toISOString();
}
