// Turns GET /ingest/status into the one line the dashboard shows. Pure, so
// the wording rules can be read (and tested) in one place.
import type { IngestStatus } from "./types";

export type FreshnessTone = "quiet" | "busy" | "warn";

export interface Freshness {
  tone: FreshnessTone;
  text: string;
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function timeAgo(iso: string, now: number): string {
  const ms = now - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < MINUTE) return "just now"; // includes small clock skew
  if (ms < HOUR) return `${plural(Math.floor(ms / MINUTE), "minute")} ago`;
  if (ms < 24 * HOUR) return `${plural(Math.floor(ms / HOUR), "hour")} ago`;
  return `${plural(Math.floor(ms / (24 * HOUR)), "day")} ago`;
}

export function everyInterval(hours: number): string {
  if (hours === 1) return "every hour";
  if (hours > 24 && hours % 24 === 0) return `every ${hours / 24} days`;
  return `every ${plural(hours, "hour")}`;
}

export function describeFreshness(s: IngestStatus, now: number): Freshness {
  if (s.running) return { tone: "busy", text: "Updating listings now…" };

  const failures = s.sources.filter((x) => x.error !== null).length;
  const failed =
    failures === 0
      ? null
      : failures === s.sources.length
        ? "the last refresh failed"
        : "part of the last refresh failed";

  if (!s.last_success_at) {
    return failed
      ? { tone: "warn", text: `Listings haven't been loaded yet · ${failed}` }
      : { tone: "quiet", text: "Listings haven't been loaded yet" };
  }

  const ago = timeAgo(s.last_success_at, now);
  const stale = now - new Date(s.last_success_at).getTime() > 2 * s.interval_hours * HOUR;

  if (failed) return { tone: "warn", text: `Listings last updated ${ago} · ${failed}` };
  if (stale) {
    // Without a schedule nothing is "overdue" — the listings are just old.
    return { tone: "warn", text: `Listings last updated ${ago}${s.auto ? " · a refresh is overdue" : ""}` };
  }
  return {
    tone: "quiet",
    text: `Listings updated ${ago}${s.auto ? ` · refreshes ${everyInterval(s.interval_hours)}` : ""}`,
  };
}

/** Exact times for the tooltip. */
export function freshnessDetail(s: IngestStatus): string {
  const when = (iso: string) =>
    new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const parts: string[] = [];
  if (s.last_success_at) parts.push(`Last updated ${when(s.last_success_at)}`);
  if (s.next_due_at) parts.push(`next refresh due ${when(s.next_due_at)}`);
  parts.push(`${s.active_postings.toLocaleString()} open listings`);
  for (const x of s.sources) if (x.error) parts.push(`${x.source}: ${x.error}`);
  return parts.join(" · ");
}
