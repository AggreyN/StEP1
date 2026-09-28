"use client";
// Applications, grouped by status with a count per group.
import { useEffect, useState } from "react";
import Link from "next/link";
import { getApplications } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { shortDate } from "@/lib/format";
import { KIND_LABELS, kindLabel, statusTone } from "@/lib/labels";
import type { ApplicationSummary } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { StatusPill } from "@/components/StatusPill";
import { CardSkeletons, ErrorNote } from "@/components/ui";

const ORDER = Object.keys(KIND_LABELS);

function groupByStatus(items: ApplicationSummary[]): [string, ApplicationSummary[]][] {
  const groups = new Map<string, ApplicationSummary[]>();
  for (const a of items) groups.set(a.status, [...(groups.get(a.status) ?? []), a]);
  const rank = (s: string) => (ORDER.indexOf(s) === -1 ? ORDER.length : ORDER.indexOf(s));
  return [...groups.entries()].sort((a, b) => rank(a[0]) - rank(b[0]));
}

export default function ApplicationsPage() {
  const authed = useRequireAuth();
  const [items, setItems] = useState<ApplicationSummary[] | null>(null);
  const [failure, setFailure] = useState<{ attempt: number; message: string } | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!authed) return;
    let cancelled = false;
    getApplications()
      .then((list) => !cancelled && setItems(list))
      .catch(
        (e: unknown) =>
          !cancelled &&
          setFailure({ attempt, message: e instanceof Error ? e.message : "Couldn't load your applications." })
      );
    return () => {
      cancelled = true;
    };
  }, [authed, attempt]);

  if (!authed) return null;
  const error = failure?.attempt === attempt ? failure.message : null;

  return (
    <AppShell>
      <div className="mb-4">
        <h1 className="text-xl font-semibold tracking-tight">Applications</h1>
        <p className="tnum text-sm text-muted">
          {items ? `${items.length} tracked` : error ? "" : "Loading…"}
        </p>
      </div>

      {error && <ErrorNote onRetry={() => setAttempt((n) => n + 1)}>{error}</ErrorNote>}

      {!items ? (
        !error && <CardSkeletons n={3} />
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-line-strong p-6 text-center">
          <p className="font-medium">No applications tracked yet.</p>
          <p className="mt-1 text-sm text-muted">
            Hit “I applied” on a posting in{" "}
            <Link href="/" className="font-medium text-accent-text underline underline-offset-2">
              your matches
            </Link>{" "}
            and its timeline starts here.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {groupByStatus(items).map(([status, group]) => {
            const quiet = statusTone(status) === "quiet";
            return (
              <section key={status} data-testid="status-group" data-status={status} aria-label={kindLabel(status)}>
                <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
                  <span className={quiet ? "text-faint" : ""}>{kindLabel(status)}</span>
                  <span
                    data-testid="group-count"
                    className="tnum rounded-full bg-surface-2 px-2 py-0.5 text-xs font-medium text-muted"
                  >
                    {group.length}
                  </span>
                </h2>
                <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
                  {group.map((a) => (
                    <li key={a.id}>
                      <Link
                        href={`/applications/${a.id}`}
                        data-testid="application-row"
                        className={`flex min-h-16 items-center gap-3 px-3.5 py-3 hover:bg-surface-2 sm:px-4 ${quiet ? "opacity-70" : ""}`}
                      >
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[15px] font-medium">{a.posting.title}</p>
                          <p className="truncate text-sm text-muted">
                            {a.posting.company.name} · applied {shortDate(a.applied_at)}
                            {a.last_event_at && a.last_event_at !== a.applied_at && ` · updated ${shortDate(a.last_event_at)}`}
                          </p>
                        </div>
                        <StatusPill status={a.status} />
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </AppShell>
  );
}
