// Dashboard filters and sort order <-> URL query params, plus the "which
// filter emptied the feed?" diagnosis used by the empty state. The diagnosis only re-calls
// GET /feed with one filter removed at a time, so it needs no special API.

import { getFeed } from "./api";
import { roleLabel } from "./roles";
import type { FeedFilters, FeedSort } from "./types";

export const EMPTY_FILTERS: FeedFilters = {
  roles: [],
  location: "",
  term: "",
  min_score: null,
  remote: false,
};

export type FilterKey = "roles" | "location" | "term" | "min_score" | "remote";

export function filtersFromParams(p: URLSearchParams): FeedFilters {
  const ms = Number(p.get("min_score"));
  return {
    roles: (p.get("roles") || "").split(",").filter(Boolean),
    location: p.get("location") || "",
    term: p.get("term") || "",
    min_score: p.get("min_score") && Number.isFinite(ms) && ms > 0 ? ms : null,
    remote: p.get("remote") === "true",
  };
}

export function filtersToParams(f: FeedFilters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.roles.length) p.set("roles", f.roles.join(","));
  if (f.location) p.set("location", f.location);
  if (f.term) p.set("term", f.term);
  if (f.min_score) p.set("min_score", String(f.min_score));
  if (f.remote) p.set("remote", "true");
  return p;
}

export const DEFAULT_SORT: FeedSort = "recent";

export const SORT_OPTIONS: { value: FeedSort; label: string; phrase: string }[] = [
  { value: "recent", label: "Newest first", phrase: "newest first" },
  { value: "score", label: "Best match", phrase: "best match first" },
];

/** Anything other than a known non-default value means the default. */
export function sortFromParams(p: URLSearchParams): FeedSort {
  return p.get("sort") === "score" ? "score" : DEFAULT_SORT;
}

/** The dashboard's whole query string. `sort` appears only when it isn't the
 *  default, so the plain URL stays the plain view. */
export function queryToParams(f: FeedFilters, sort: FeedSort): URLSearchParams {
  const p = filtersToParams(f);
  if (sort !== DEFAULT_SORT) p.set("sort", sort);
  return p;
}

export function activeFilterKeys(f: FeedFilters): FilterKey[] {
  const keys: FilterKey[] = [];
  if (f.roles.length) keys.push("roles");
  if (f.location) keys.push("location");
  if (f.term) keys.push("term");
  if (f.min_score) keys.push("min_score");
  if (f.remote) keys.push("remote");
  return keys;
}

export function withoutFilter(f: FeedFilters, key: FilterKey): FeedFilters {
  return { ...f, [key]: EMPTY_FILTERS[key] };
}

export const FILTER_NAMES: Record<FilterKey, string> = {
  roles: "role filter",
  location: "location filter",
  term: "term filter",
  min_score: "minimum score",
  remote: "remote-only filter",
};

function listJoin(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return items.slice(0, -1).join(", ") + " or " + items[items.length - 1];
}

/** "Security postings in Seattle for Fall 2027 scoring 80+" (no leading count). */
export function describe(f: FeedFilters, omit?: FilterKey): string {
  const remote = f.remote && omit !== "remote" ? "remote " : "";
  const roles = f.roles.length && omit !== "roles" ? listJoin(f.roles.map(roleLabel)) + " " : "";
  let s = `${remote}${roles}postings`;
  if (f.location && omit !== "location") s += ` in ${f.location}`;
  if (f.term && omit !== "term") s += ` for ${f.term}`;
  if (f.min_score && omit !== "min_score") s += ` scoring ${f.min_score}+`;
  return s;
}

const RELAXED_SUFFIX: Record<FilterKey, string> = {
  roles: "in other fields",
  location: "elsewhere",
  term: "in other terms",
  min_score: "at lower scores",
  remote: "including on-site",
};

export interface Relaxation {
  key: FilterKey;
  total: number;
  /** "12 Security postings elsewhere" */
  sentence: string;
}

/** For a filtered query that returned 0, try dropping each active filter once
 *  (page_size=1, we only need `total`). Returns the removals that help,
 *  largest first. */
export async function diagnoseEmpty(f: FeedFilters, sort: FeedSort = DEFAULT_SORT): Promise<Relaxation[]> {
  const keys = activeFilterKeys(f);
  const results = await Promise.all(
    keys.map(async (key) => {
      try {
        const page = await getFeed(withoutFilter(f, key), 1, 1, sort);
        return { key, total: page.total };
      } catch {
        return { key, total: 0 };
      }
    })
  );
  return results
    .filter((r) => r.total > 0)
    .sort((a, b) => b.total - a.total)
    .map((r) => {
      const phrase = describe(f, r.key);
      const noun = r.total === 1 ? phrase.replace("postings", "posting") : phrase;
      return { ...r, sentence: `${r.total} ${noun} ${RELAXED_SUFFIX[r.key]}` };
    });
}
