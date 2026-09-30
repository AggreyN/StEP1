"use client";
// The owner's page: every review, newest first. Anyone else sees the
// not-found page, as if it didn't exist (the API answers them 404 too).
import { useEffect, useState } from "react";
import { ApiError, getAdminReviews } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { useMe } from "@/lib/me";
import type { AdminReviewPage } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { NotFound } from "@/components/NotFound";
import { Stars } from "@/components/StarRating";
import { Button, ErrorNote, Spinner } from "@/components/ui";

function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function AdminPage() {
  const authed = useRequireAuth();
  const me = useMe();
  const [data, setData] = useState<AdminReviewPage | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const admin = me?.is_admin === true;

  useEffect(() => {
    if (!admin) return;
    let cancelled = false;
    getAdminReviews(1)
      .then((page) => !cancelled && setData(page))
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) setMissing(true);
        else setError(e instanceof Error ? e.message : "Couldn't load the reviews.");
      });
    return () => {
      cancelled = true;
    };
  }, [admin]);

  async function loadMore() {
    if (!data) return;
    setLoadingMore(true);
    try {
      const next = await getAdminReviews(data.page + 1);
      setData((d) => d && { ...next, items: [...d.items, ...next.items.filter((r) => !d.items.some((x) => x.id === r.id))] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load more.");
    } finally {
      setLoadingMore(false);
    }
  }

  if (!authed) return null;
  if ((me && !me.is_admin) || missing) return <NotFound />;

  return (
    <AppShell>
      <h1 className="text-xl font-semibold tracking-tight">Reviews</h1>

      {error && (
        <div className="mt-3">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}

      {!data ? (
        !error && (
          <div className="mt-4">
            <Spinner label="Loading reviews" />
          </div>
        )
      ) : (
        <>
          <dl className="mt-3 flex flex-wrap gap-x-8 gap-y-2 border-y border-line py-3" data-testid="review-summary">
            <div>
              <dt className="text-xs uppercase tracking-wide text-faint">Reviews</dt>
              <dd className="font-mono text-xl font-medium" data-testid="review-total">
                {data.total.toLocaleString()}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-faint">Average rating</dt>
              <dd className="flex items-center gap-2 font-mono text-xl font-medium" data-testid="review-average">
                {data.average_rating === null ? (
                  "None yet"
                ) : (
                  <>
                    {data.average_rating.toFixed(1)}
                    <span className="font-ui text-sm font-normal text-muted">out of 5</span>
                  </>
                )}
              </dd>
            </div>
          </dl>

          {data.items.length === 0 ? (
            <p className="mt-4 text-sm text-muted">No reviews yet.</p>
          ) : (
            <ul className="mt-4 space-y-3" aria-label="Reviews, newest first">
              {data.items.map((r) => (
                <li key={r.id} data-testid="admin-review" className="rounded-card border border-line bg-surface p-3.5 sm:p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <Stars rating={r.rating} />
                    <time dateTime={r.created_at} className="font-mono text-[13px] text-faint">
                      {when(r.created_at)}
                    </time>
                  </div>
                  {/* Plain text: React escapes it, and line breaks are kept by CSS. */}
                  <p className="mt-2 whitespace-pre-wrap break-words text-[15px]" data-testid="admin-review-body">
                    {r.body}
                  </p>
                  <p className="mt-2 text-sm text-muted" data-testid="admin-review-author">
                    {r.user ? (
                      <>
                        {r.user.display_name && <span className="font-medium text-fg">{r.user.display_name} </span>}
                        <a href={`mailto:${r.user.email}`} className="text-accent-text underline underline-offset-2 break-all">
                          {r.user.email}
                        </a>
                      </>
                    ) : (
                      <span className="italic">Deleted account</span>
                    )}
                  </p>
                </li>
              ))}
            </ul>
          )}

          {data.has_more && (
            <div className="mt-5 flex justify-center">
              <Button onClick={loadMore} busy={loadingMore} data-testid="load-more-reviews">
                {loadingMore ? "Loading…" : `Load more (${data.total - data.items.length} left)`}
              </Button>
            </div>
          )}
        </>
      )}
    </AppShell>
  );
}
