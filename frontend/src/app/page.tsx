"use client";
// Dashboard: the scored, sorted feed. Filters live in the URL so a filtered
// view is linkable and survives reload.
import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ApiError, getFeed } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import {
  EMPTY_FILTERS,
  FILTER_NAMES,
  activeFilterKeys,
  describe,
  diagnoseEmpty,
  filtersFromParams,
  filtersToParams,
  withoutFilter,
  type Relaxation,
} from "@/lib/filters";
import type { FeedFilters, Page, Posting } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { Dialog } from "@/components/Dialog";
import { FilterPanel } from "@/components/FilterPanel";
import { PostingList } from "@/components/PostingList";
import { FilterIcon } from "@/components/icons";
import { Button, CardSkeletons, ErrorNote, Spinner } from "@/components/ui";

function Dashboard() {
  const authed = useRequireAuth();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const filters = filtersFromParams(params);
  const filterKey = filtersToParams(filters).toString();

  // Results are stored with the query they answer, so "loading" is derived
  // (the stored key doesn't match the current one) rather than set by hand.
  const [reload, setReload] = useState(0);
  const key = `${filterKey}#${reload}`;
  const [data, setData] = useState<{ key: string; page: Page<Posting> } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [relaxed, setRelaxed] = useState<{ key: string; list: Relaxation[] } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);

  // A filter change shows in the controls immediately and is written to the
  // URL (replaceState: no server round trip, and Next keeps useSearchParams in
  // sync). `pending` only bridges the moment before the URL catches up.
  const [pending, setPending] = useState<{ from: string; to: FeedFilters } | null>(null);
  if (pending && (pending.from !== filterKey || filtersToParams(pending.to).toString() === filterKey)) {
    setPending(null);
  }
  const shown = pending ? pending.to : filters;

  const setFilters = useCallback(
    (f: FeedFilters) => {
      const qs = filtersToParams(f).toString();
      if (qs === filterKey) return;
      setPending({ from: filterKey, to: f });
      window.history.replaceState(null, "", qs ? `${pathname}?${qs}` : pathname);
    },
    [filterKey, pathname]
  );

  // Fetch page 1 whenever the URL filters change.
  useEffect(() => {
    if (!authed) return;
    let cancelled = false;
    const f = filtersFromParams(new URLSearchParams(key.split("#")[0]));
    getFeed(f, 1)
      .then(async (page) => {
        if (cancelled) return;
        setData({ key, page });
        if (page.total === 0 && activeFilterKeys(f).length) {
          const list = await diagnoseEmpty(f);
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
      const res = await getFeed(filters, current.page + 1);
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

  return (
    <AppShell wide>
      <div className="lg:grid lg:grid-cols-[15rem_minmax(0,1fr)] lg:gap-8">
        <aside className="hidden lg:block">
          <div className="sticky top-20">
            <FilterPanel value={shown} onChange={setFilters} />
          </div>
        </aside>

        <section className="min-w-0">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h1 className="text-xl font-semibold tracking-tight">Your matches</h1>
              <p className="tnum text-sm text-muted" data-testid="feed-total">
                {loading ? "Ranking…" : `${countLabel}${activeCount ? ` match${total === 1 ? "es" : ""} your filters` : ", best match first"}`}
              </p>
            </div>
            <Button size="sm" className="lg:hidden" onClick={() => setSheetOpen(true)} data-testid="open-filters">
              <FilterIcon />
              Filters{activeCount ? ` · ${activeCount}` : ""}
            </Button>
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
        <FilterPanel value={shown} onChange={setFilters} />
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
