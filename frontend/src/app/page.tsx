"use client";
// Dashboard: the feed, newest first by default. Filters and sort order live in
// the URL so a view is linkable and survives reload.
import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ApiError, PAGE_SIZE, getFeed } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import {
  EMPTY_FILTERS,
  FILTER_NAMES,
  SORT_OPTIONS,
  activeFilterKeys,
  describe,
  diagnoseEmpty,
  filtersFromParams,
  queryToParams,
  sortFromParams,
  withoutFilter,
  type Relaxation,
} from "@/lib/filters";
import type { FeedFilters, FeedSort, Page, Posting } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { Dialog } from "@/components/Dialog";
import { FilterPanel } from "@/components/FilterPanel";
import { FreshnessLine } from "@/components/FreshnessLine";
import { PostingList } from "@/components/PostingList";
import { SortControl } from "@/components/SortControl";
import { FilterIcon } from "@/components/icons";
import { Button, CardSkeletons, ErrorNote, Spinner } from "@/components/ui";

function Dashboard() {
  const authed = useRequireAuth();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const filters = filtersFromParams(params);
  const sort = sortFromParams(params);
  const queryKey = queryToParams(filters, sort).toString();

  // Results are stored with the query they answer, so "loading" is derived
  // (the stored key doesn't match the current one) rather than set by hand.
  // The key covers filters and sort, so changing either starts again at page 1.
  const [reload, setReload] = useState(0);
  const key = `${queryKey}#${reload}`;
  const [data, setData] = useState<{ key: string; page: Page<Posting> } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [relaxed, setRelaxed] = useState<{ key: string; list: Relaxation[] } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);

  // A change shows in the controls immediately and is written to the URL
  // (replaceState: no server round trip, and Next keeps useSearchParams in
  // sync). `pending` only bridges the moment before the URL catches up.
  const [pending, setPending] = useState<{ from: string; filters: FeedFilters; sort: FeedSort } | null>(null);
  if (
    pending &&
    (pending.from !== queryKey || queryToParams(pending.filters, pending.sort).toString() === queryKey)
  ) {
    setPending(null);
  }
  const shown = pending ? pending.filters : filters;
  const shownSort = pending ? pending.sort : sort;

  const setQuery = useCallback(
    (f: FeedFilters, s: FeedSort) => {
      const qs = queryToParams(f, s).toString();
      if (qs === queryKey) return;
      setPending({ from: queryKey, filters: f, sort: s });
      window.history.replaceState(null, "", qs ? `${pathname}?${qs}` : pathname);
    },
    [queryKey, pathname]
  );
  const setFilters = useCallback((f: FeedFilters) => setQuery(f, shownSort), [setQuery, shownSort]);
  const setSort = useCallback((s: FeedSort) => setQuery(shown, s), [setQuery, shown]);

  // Fetch page 1 whenever the URL's filters or sort change.
  useEffect(() => {
    if (!authed) return;
    let cancelled = false;
    const q = new URLSearchParams(key.split("#")[0]);
    const f = filtersFromParams(q);
    const s = sortFromParams(q);
    getFeed(f, 1, PAGE_SIZE, s)
      .then(async (page) => {
        if (cancelled) return;
        setData({ key, page });
        if (page.total === 0 && activeFilterKeys(f).length) {
          const list = await diagnoseEmpty(f, s);
          if (!cancelled) setRelaxed({ key, list });
        }
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 409) {
          router.replace("/onboarding");
          return;
        }
        setFailure({ key, message: e instanceof Error ? e.message : "Couldn't load your matches." });
      });
    return () => {
      cancelled = true;
    };
  }, [authed, key, router]);

  const current = data?.key === key ? data.page : null;
  const error = failure?.key === key ? failure.message : null;
  const loading = !current && !error;
  const items = current?.items ?? [];
  const total = current?.total ?? 0;
  const hasMore = current?.has_more ?? false;
  const relaxations = relaxed?.key === key ? relaxed.list : null;

  const patch = useCallback((id: string, fn: (p: Posting) => Posting) => {
    setData((d) => d && { ...d, page: { ...d.page, items: d.page.items.map((p) => (p.id === id ? fn(p) : p)) } });
  }, []);

  async function loadMore() {
    if (!current) return;
    setLoadingMore(true);
    try {
      const res = await getFeed(filters, current.page + 1, PAGE_SIZE, sort);
      setData((d) => {
        if (!d || d.key !== key) return d;
        const seen = new Set(d.page.items.map((p) => p.id));
        return { key, page: { ...res, items: [...d.page.items, ...res.items.filter((p) => !seen.has(p.id))] } };
      });
    } catch (e) {
      setFailure({ key, message: e instanceof Error ? e.message : "Couldn't load more." });
    } finally {
      setLoadingMore(false);
    }
  }

  if (!authed) return null;

  const activeCount = activeFilterKeys(shown).length;
  const countLabel = `${total} posting${total === 1 ? "" : "s"}`;
  const order = SORT_OPTIONS.find((o) => o.value === sort)?.phrase ?? "";
  const summary = activeCount
    ? `${countLabel} match${total === 1 ? "es" : ""} your filters, ${order}`
    : `${countLabel}, ${order}`;

  return (
    <AppShell wide>
      <div className="lg:grid lg:grid-cols-[15rem_minmax(0,1fr)] lg:gap-8">
        <aside className="hidden lg:block">
          <div className="sticky top-20">
            <FilterPanel value={shown} onChange={setFilters} />
          </div>
        </aside>

        <section className="min-w-0">
          {/* Heading on the left; sort (and, below lg, the Filters button) on
              the right. On a phone the controls wrap onto their own row. */}
          <div className="mb-3 flex flex-wrap items-end justify-between gap-x-4 gap-y-2.5">
            <div className="min-w-0">
              <h1 className="text-xl font-semibold tracking-tight">Your matches</h1>
              <p className="tnum text-sm text-muted" data-testid="feed-total">
                {loading ? "Loading…" : summary}
              </p>
              <FreshnessLine />
            </div>
            <div className="flex w-full items-center justify-between gap-2 sm:w-auto sm:justify-end">
              <SortControl value={shownSort} onChange={setSort} />
              <Button size="sm" className="lg:hidden" onClick={() => setSheetOpen(true)} data-testid="open-filters">
                <FilterIcon />
                Filters{activeCount ? ` · ${activeCount}` : ""}
              </Button>
            </div>
          </div>

          {error && (
            <div className="mb-3">
              <ErrorNote onRetry={() => setReload((n) => n + 1)}>{error}</ErrorNote>
            </div>
          )}

          {loading ? (
            <CardSkeletons />
          ) : !current ? null : items.length === 0 ? (
            <EmptyState filters={filters} relaxations={relaxations} onRelax={setFilters} />
          ) : (
            <>
              <PostingList items={items} onPatch={patch} />
              {hasMore && (
                <div className="mt-5 flex justify-center">
                  <Button onClick={loadMore} disabled={loadingMore} data-testid="load-more">
                    {loadingMore ? "Loading…" : `Load more (${total - items.length} left)`}
                  </Button>
                </div>
              )}
            </>
          )}
        </section>
      </div>

      <Dialog open={sheetOpen} onClose={() => setSheetOpen(false)} title="Filters" sheet>
        <FilterPanel value={shown} onChange={setFilters} heading={false} />
        <Button variant="primary" className="mt-5 w-full" onClick={() => setSheetOpen(false)} data-testid="close-filters">
          {loading ? "Show results" : `Show ${countLabel}`}
        </Button>
      </Dialog>
    </AppShell>
  );
}

function EmptyState({
  filters,
  relaxations,
  onRelax,
}: {
  filters: FeedFilters;
  relaxations: Relaxation[] | null;
  onRelax: (f: FeedFilters) => void;
}) {
  const active = activeFilterKeys(filters);
  if (!active.length) {
    return (
      <div data-testid="empty-state" className="rounded-xl border border-dashed border-line-strong p-6 text-center">
        <p className="font-medium">No matches yet.</p>
        <p className="mt-1 text-sm text-muted">
          Postings are matched against your fields, terms and degree.{" "}
          <Link href="/onboarding" className="font-medium text-accent-text underline underline-offset-2">
            Check your profile
          </Link>
          .
        </p>
      </div>
    );
  }
  return (
    <div data-testid="empty-state" className="rounded-xl border border-dashed border-line-strong p-5">
      <p className="font-medium">No {describe(filters)}.</p>
      {relaxations === null ? (
        <div className="mt-3">
          <Spinner label="Checking which filter is responsible…" />
        </div>
      ) : relaxations.length ? (
        <ul className="mt-3 space-y-2" data-testid="relaxations">
          {relaxations.map((r) => (
            <li key={r.key} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="tnum min-w-0 text-muted">{r.sentence}</span>
              <Button size="sm" onClick={() => onRelax(withoutFilter(filters, r.key))} data-testid={`relax-${r.key}`}>
                Remove {FILTER_NAMES[r.key]}
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm">
          <span className="min-w-0 text-muted" data-testid="no-single-filter">
            No single filter is responsible — removing any one of the{" "}
            {active.map((k) => FILTER_NAMES[k]).join(", ")} still finds nothing. They&apos;re too narrow together.
          </span>
          <Button size="sm" onClick={() => onRelax(EMPTY_FILTERS)}>
            Clear all filters
          </Button>
        </div>
      )}
    </div>
  );
}

export default function DashboardPage() {
  return (
    <Suspense>
      <Dashboard />
    </Suspense>
  );
}
