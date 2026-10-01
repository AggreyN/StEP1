"use client";
// The Users tab of /admin: everyone with an account, searchable.
import { useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, getAdminUsers } from "@/lib/api";
import type { AdminUserRow, Page } from "@/lib/types";
import { Button, ErrorNote, Spinner } from "../ui";
import { when } from "./AdminReviews";

export function AdminUsers({ onMissing, query, onQuery }: { onMissing: () => void; query: string; onQuery: (q: string) => void }) {
  const [draft, setDraft] = useState(query);
  const [data, setData] = useState<{ query: string; page: Page<AdminUserRow> } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  // Searching as you type, without a request per key.
  useEffect(() => {
    if (draft.trim() === query.trim()) return;
    const t = setTimeout(() => onQuery(draft.trim()), 300);
    return () => clearTimeout(t);
  }, [draft, query, onQuery]);

  useEffect(() => {
    let cancelled = false;
    getAdminUsers(query, 1)
      .then((page) => !cancelled && setData({ query, page }))
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) onMissing();
        else setError(e instanceof Error ? e.message : "Couldn't load people.");
      });
    return () => {
      cancelled = true;
    };
  }, [query, onMissing]);

  async function loadMore() {
    if (!data) return;
    setLoadingMore(true);
    try {
      const next = await getAdminUsers(data.query, data.page.page + 1);
      setData((d) =>
        d && d.query === data.query
          ? { query: d.query, page: { ...next, items: [...d.page.items, ...next.items.filter((r) => !d.page.items.some((x) => x.id === r.id))] } }
          : d
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load more.");
    } finally {
      setLoadingMore(false);
    }
  }

  const current = data?.query === query ? data.page : null;

  return (
    <>
      <h2 className="text-lg font-semibold tracking-tight">Users</h2>
      <label className="mt-3 block max-w-md">
        <span className="mb-1 block text-sm font-medium">Search</span>
        <input
          type="search"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Name, email, school or major"
          className="h-11 w-full rounded-control border border-line-strong bg-surface px-3 text-[15px] placeholder:text-faint"
          data-testid="people-search"
        />
      </label>

      {error && (
        <div className="mt-3">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}

      {!current ? (
        !error && (
          <div className="mt-4">
            <Spinner label="Loading people" />
          </div>
        )
      ) : (
        <>
          <p className="mt-3 font-mono text-sm text-muted" data-testid="people-total">
            {current.total.toLocaleString()} {current.total === 1 ? "person" : "people"}
            {query ? ` matching “${query}”` : ""}
          </p>
          {current.items.length === 0 ? (
            <p className="mt-3 text-sm text-muted">Nobody matches that search.</p>
          ) : (
            <ul className="mt-3 divide-y divide-line overflow-hidden rounded-card border border-line bg-surface" aria-label="Users">
              {current.items.map((u) => (
                <li key={u.id}>
                  <Link
                    href={`/admin/user?id=${u.id}`}
                    data-testid="person-row"
                    className="block px-3.5 py-3 hover:bg-surface-2 sm:px-4"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                      <span className="min-w-0 break-words text-[15px] font-medium">{u.display_name ?? u.email}</span>
                      <span className="font-mono text-[13px] text-faint">
                        {u.last_active_at ? `active ${when(u.last_active_at)}` : "never active"}
                      </span>
                    </div>
                    {u.display_name && <p className="break-all text-sm text-muted">{u.email}</p>}
                    <p className="text-sm text-muted">
                      {u.onboarded
                        ? [u.school, u.major, u.grad_year && `class of ${u.grad_year}`].filter(Boolean).join(" · ")
                        : "Hasn't finished signing up"}
                    </p>
                    <p className="mt-1 flex flex-wrap gap-x-3 font-mono text-[13px] text-muted">
                      <span>{u.applications} applied</span>
                      <span>{u.saved} saved</span>
                      <span>{u.tailored_resumes} tailored</span>
                      <span>{u.has_resume ? "resume uploaded" : "no resume"}</span>
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {current.has_more && (
            <div className="mt-5 flex justify-center">
              <Button onClick={loadMore} busy={loadingMore} data-testid="load-more-people">
                {loadingMore ? "Loading…" : `Load more (${current.total - current.items.length} left)`}
              </Button>
            </div>
          )}
        </>
      )}
    </>
  );
}
