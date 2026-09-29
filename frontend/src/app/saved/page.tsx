"use client";
// Saved postings: the same cards, filtered to saved. Un-starring is
// optimistic; the card leaves the list once the API confirms, and comes back
// starred if the call fails.
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, getSaved } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { Page, Posting } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { PostingList } from "@/components/PostingList";
import { Button, CardSkeletons, ErrorNote } from "@/components/ui";

export default function SavedPage() {
  const authed = useRequireAuth();
  const router = useRouter();
  const [data, setData] = useState<Page<Posting> | null>(null);
  const [failure, setFailure] = useState<{ attempt: number; message: string } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);

  useEffect(() => {
    if (!authed) return;
    let cancelled = false;
    getSaved(1)
      .then((page) => !cancelled && setData(page))
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 409) {
          router.replace("/onboarding");
          return;
        }
        setFailure({ attempt, message: e instanceof Error ? e.message : "Couldn't load your saved postings." });
      });
    return () => {
      cancelled = true;
    };
  }, [authed, attempt, router]);

  const patch = useCallback((id: string, fn: (p: Posting) => Posting) => {
    setData((d) => d && { ...d, items: d.items.map((p) => (p.id === id ? fn(p) : p)) });
  }, []);

  const removed = useCallback((id: string) => {
    setData((d) => d && { ...d, items: d.items.filter((p) => p.id !== id), total: Math.max(0, d.total - 1) });
  }, []);

  async function loadMore() {
    if (!data) return;
    setLoadingMore(true);
    try {
      const res = await getSaved(data.page + 1);
      setData((d) => {
        if (!d) return d;
        const seen = new Set(d.items.map((p) => p.id));
        return { ...res, items: [...d.items, ...res.items.filter((p) => !seen.has(p.id))] };
      });
    } catch (e) {
      setFailure({ attempt, message: e instanceof Error ? e.message : "Couldn't load more." });
    } finally {
      setLoadingMore(false);
    }
  }

  if (!authed) return null;
  const error = failure?.attempt === attempt ? failure.message : null;

  return (
    <AppShell>
      <div className="mb-3">
        <h1 className="text-xl font-semibold tracking-tight">Saved</h1>
        <p className="tnum text-sm text-muted">
          {data ? `${data.total} saved posting${data.total === 1 ? "" : "s"}` : error ? "" : "Loading…"}
        </p>
      </div>

      {error && (
        <div className="mb-3">
          <ErrorNote onRetry={() => setAttempt((n) => n + 1)}>{error}</ErrorNote>
        </div>
      )}

      {!data ? (
        !error && <CardSkeletons n={3} />
      ) : data.items.length === 0 ? (
        <div data-testid="saved-empty" className="rounded-card border border-dashed border-line-strong p-6 text-center">
          <p className="font-medium">Nothing saved yet.</p>
          <p className="mt-1 text-sm text-muted">
            Star a posting on{" "}
            <Link href="/" className="font-medium text-accent-text underline underline-offset-2">
              your matches
            </Link>{" "}
            to keep it here.
          </p>
        </div>
      ) : (
        <>
          <PostingList items={data.items} onPatch={patch} onUnsaved={removed} />
          {data.has_more && (
            <div className="mt-5 flex justify-center">
              <Button onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? "Loading…" : "Load more"}
              </Button>
            </div>
          )}
        </>
      )}
    </AppShell>
  );
}
