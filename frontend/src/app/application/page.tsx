"use client";
// Application detail: the timeline, at /application?id=12.
//
// The id is in the query string so that this is one static file for every
// application. Old-style addresses, /applications/12, have no file; the
// not-found page sends them here (see components/NotFound.tsx).
//
// The buttons under the timeline are rendered from the API's
// `next_transitions`. This page has no idea which state may follow which.
import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ApiError, getApplication } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { formatSalary, longDate } from "@/lib/format";
import { kindLabel, statusTone } from "@/lib/labels";
import type { ApplicationDetail } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { EventDialog } from "@/components/EventDialog";
import { ScoreBadge } from "@/components/ScoreBadge";
import { StatusPill } from "@/components/StatusPill";
import { Timeline } from "@/components/Timeline";
import { ExternalIcon } from "@/components/icons";
import { Button, ErrorNote, Spinner } from "@/components/ui";

function ApplicationDetail() {
  const authed = useRequireAuth();
  const id = useSearchParams().get("id") ?? "";

  const [loaded, setLoaded] = useState<{ id: string; detail: ApplicationDetail } | null>(null);
  const [failure, setFailure] = useState<{ id: string; message: string; missing: boolean } | null>(null);
  const [dialogKind, setDialogKind] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const nextHeading = useRef<HTMLHeadingElement>(null);
  // Counts recorded events. After each one, focus moves to the "What happened
  // next?" heading: the button that opened the dialog may no longer exist.
  const [recorded, setRecorded] = useState(0);
  useEffect(() => {
    if (!recorded) return;
    const frame = requestAnimationFrame(() => nextHeading.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [recorded]);

  useEffect(() => {
    if (!authed || !id) return;
    let cancelled = false;
    getApplication(id)
      .then((detail) => !cancelled && setLoaded({ id, detail }))
      .catch(
        (e: unknown) =>
          !cancelled &&
          setFailure({
            id,
            message: e instanceof Error ? e.message : "Couldn't load this application.",
            missing: e instanceof ApiError && e.status === 404,
          })
      );
    return () => {
      cancelled = true;
    };
  }, [authed, id]);

  if (!authed) return null;

  const app = loaded?.id === id ? loaded.detail : null;
  const error = !id
    ? { id, message: "This link doesn't say which application to show.", missing: true }
    : failure?.id === id
      ? failure
      : null;

  return (
    <AppShell>
      <Link href="/applications" className="mb-3 inline-block text-sm text-muted hover:text-fg">
        ← All applications
      </Link>

      {error ? (
        <>
          <h1 className="mb-3 text-xl font-semibold tracking-tight">
            {error.missing ? "Application not found" : "Application"}
          </h1>
          <ErrorNote>{error.message}</ErrorNote>
        </>
      ) : !app ? (
        <>
          <h1 className="mb-3 text-xl font-semibold tracking-tight">Application</h1>
          <Spinner label="Loading timeline" />
        </>
      ) : (
        <div className="space-y-4">
          <header className="rounded-card border border-line bg-surface p-4">
            <div className="flex items-start gap-3">
              <ScoreBadge score={app.posting.score} />
              <div className="min-w-0 flex-1">
                <h1 className="text-lg font-semibold leading-snug tracking-tight">{app.posting.title}</h1>
                <p className="text-sm text-muted">
                  <span className="font-medium text-fg">{app.posting.company.name}</span>
                  {app.posting.locations.length > 0 && ` · ${app.posting.locations.slice(0, 2).join(" · ")}`}
                  {app.posting.terms.length > 0 && ` · ${app.posting.terms[0]}`}
                  {formatSalary(app.posting.salary) && ` · ${formatSalary(app.posting.salary)}`}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
                  <StatusPill status={app.status} />
                  <span className="text-muted">Applied {longDate(app.applied_at)}</span>
                  <a
                    href={app.posting.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-muted underline-offset-2 hover:text-fg hover:underline"
                  >
                    Original posting <ExternalIcon />
                  </a>
                  <Link
                    href={`/tailor?posting=${encodeURIComponent(app.posting.id)}`}
                    data-testid="tailor-button"
                    className="font-medium text-accent-text underline underline-offset-2"
                  >
                    Tailor resume
                  </Link>
                </div>
              </div>
            </div>
          </header>

          <section className="rounded-card border border-line bg-surface p-4" aria-label="Timeline">
            <h2 className="mb-4 text-xs font-semibold uppercase tracking-wide text-faint">Timeline</h2>
            <Timeline events={app.events} status={app.status} />
          </section>

          <section className="rounded-card border border-line bg-surface p-4" aria-label="Next steps">
            <h2 ref={nextHeading} tabIndex={-1} className="text-base font-semibold outline-none">
              What happened next?
            </h2>
            {app.next_transitions.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2" data-testid="transitions">
                {app.next_transitions.map((kind) => {
                  const tone = statusTone(kind);
                  return (
                    <Button
                      key={kind}
                      variant={tone === "negative" ? "danger" : tone === "quiet" ? "ghost" : "secondary"}
                      onClick={() => setDialogKind(kind)}
                      data-testid="transition-button"
                      data-kind={kind}
                    >
                      {kindLabel(kind)}
                    </Button>
                  );
                })}
              </div>
            ) : (
              <p className="mt-1 text-sm text-muted" data-testid="no-transitions">
                This application is closed, so there&apos;s nothing further to record. You can still add notes.
              </p>
            )}
            <div className="mt-3 border-t border-line pt-3">
              <Button variant="ghost" size="sm" onClick={() => setDialogKind("note")} data-testid="add-note">
                + Add note
              </Button>
            </div>
          </section>

          <EventDialog
            applicationId={app.id}
            kind={dialogKind}
            onClose={() => setDialogKind(null)}
            onSaved={(detail) => {
              setAnnouncement(
                dialogKind === "note" ? "Note added." : `Recorded. This application is now: ${kindLabel(detail.status)}.`
              );
              setLoaded({ id, detail });
              setDialogKind(null);
              setRecorded((n) => n + 1);
            }}
          />
          <p className="sr-only" role="status" aria-live="polite" data-testid="timeline-announcement">
            {announcement}
          </p>
        </div>
      )}
    </AppShell>
  );
}

export default function ApplicationPage() {
  return (
    <Suspense>
      <ApplicationDetail />
    </Suspense>
  );
}
