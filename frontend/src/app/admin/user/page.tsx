"use client";
// One person's data, for the owner: /admin/user?id=12. The id is in the
// query string so this is one static file for everyone. Everything shown
// is the person's own words, rendered as plain text, never as HTML.
import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ApiError, getAdminUser, getAdminUserResumeFile } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { useMe } from "@/lib/me";
import type { AdminUserDetail } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { NotFound } from "@/components/NotFound";
import { Stars } from "@/components/StarRating";
import { StatusPill } from "@/components/StatusPill";
import { Timeline } from "@/components/Timeline";
import { when } from "@/components/admin/AdminReviews";
import { Button, ErrorNote, Spinner } from "@/components/ui";

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="rounded-card border border-line bg-surface p-3.5 sm:p-5" aria-label={title}>
      <h2 className="text-base font-semibold">
        {title}
        {count !== undefined && <span className="ml-2 font-mono text-sm font-normal text-muted">{count}</span>}
      </h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 py-1 text-sm sm:grid-cols-[10rem_minmax(0,1fr)]">
      <dt className="text-muted">{label}</dt>
      <dd className="m-0 min-w-0 break-words">{value === null || value === "" ? <span className="text-faint">none</span> : value}</dd>
    </div>
  );
}

const nothing = (what: string) => <p className="text-sm text-muted">{what}</p>;

function UserDetail() {
  const authed = useRequireAuth();
  const me = useMe();
  const id = useSearchParams().get("id") ?? "";
  const [data, setData] = useState<{ id: string; detail: AdminUserDetail } | null>(null);
  const [failure, setFailure] = useState<{ id: string; missing: boolean; message: string } | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [fetchingFile, setFetchingFile] = useState(false);
  const admin = me?.is_admin === true;

  useEffect(() => {
    if (!admin || !id) return;
    let cancelled = false;
    getAdminUser(id)
      .then((detail) => !cancelled && setData({ id, detail }))
      .catch((e: unknown) => {
        if (cancelled) return;
        setFailure({
          id,
          missing: e instanceof ApiError && e.status === 404,
          message: e instanceof Error ? e.message : "Couldn't load this person.",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [admin, id]);

  const downloadUploaded = useCallback(async () => {
    setFetchingFile(true);
    setFileError(null);
    try {
      const link = await getAdminUserResumeFile(id);
      // The link is short-lived and made for this one download.
      const a = document.createElement("a");
      a.href = link.url;
      a.download = link.filename;
      a.rel = "noopener noreferrer";
      document.body.append(a);
      a.click();
      a.remove();
    } catch (e) {
      setFileError(e instanceof Error ? e.message : "Couldn't get the file.");
    } finally {
      setFetchingFile(false);
    }
  }, [id]);

  if (!authed) return null;
  if (me && !me.is_admin) return <NotFound />;
  // An unknown person: the admin's own not-found message, inside the shell.
  const error = !id
    ? { missing: true, message: "This link doesn't say which person to show." }
    : failure?.id === id
      ? failure
      : null;
  const d = data?.id === id ? data.detail : null;
  const name = d ? (d.user.display_name ?? d.user.email) : "";

  return (
    <AppShell>
      <Link href="/admin?tab=users" className="mb-3 inline-block text-sm text-muted hover:text-fg">
        ← All users
      </Link>

      {error ? (
        <>
          <h1 className="mb-3 text-xl font-semibold tracking-tight">{error.missing ? "No such person" : "User"}</h1>
          <ErrorNote>{error.missing ? "There is nobody with that id." : error.message}</ErrorNote>
        </>
      ) : !d ? (
        <>
          <h1 className="mb-3 text-xl font-semibold tracking-tight">User</h1>
          <Spinner label="Loading" />
        </>
      ) : (
        <div className="space-y-4">
          <div
            role="note"
            data-testid="viewing-banner"
            className="rounded-card border border-warn bg-warn-soft px-3.5 py-3 text-sm text-fg sm:px-4"
          >
            <p className="font-semibold">You are viewing another person&apos;s data.</p>
            <p className="mt-0.5 text-muted">
              This is {name}&apos;s account. Nothing here is shown to them or changed by looking.
            </p>
          </div>

          <header>
            <h1 className="break-words text-xl font-semibold tracking-tight" data-testid="person-name">
              {name}
            </h1>
            <p className="break-all text-sm text-muted">{d.user.email}</p>
          </header>

          <Section title="Account">
            <dl className="m-0">
              <Row label="Joined" value={when(d.user.created_at)} />
              <Row label="Display name" value={d.user.display_name} />
              <Row label="Admin" value={d.user.is_admin ? "Yes" : "No"} />
            </dl>
          </Section>

          <Section title="Profile">
            {d.profile ? (
              <dl className="m-0">
                <Row label="School" value={d.profile.school} />
                <Row label="Major" value={d.profile.major} />
                <Row label="Minor" value={d.profile.minor} />
                <Row label="Degree" value={d.profile.degree_level} />
                <Row label="Graduates" value={d.profile.grad_year ? String(d.profile.grad_year) : null} />
                <Row
                  label="Looking for"
                  value={(d.profile.looking_for ?? []).map((k) => (k === "new_grad" ? "New grad roles" : "Internships")).join(", ")}
                />
                <Row label="Terms" value={d.profile.target_terms.join(", ")} />
                <Row
                  label="Locations"
                  value={[...d.profile.preferred_locations, d.profile.remote_ok ? "remote is fine" : ""].filter(Boolean).join(", ")}
                />
                <Row
                  label="Fields"
                  value={[...d.profile.interests]
                    .sort((a, b) => a.rank - b.rank)
                    .map((i) => `${i.rank}. ${i.label ?? i.role}`)
                    .join(", ")}
                />
              </dl>
            ) : (
              nothing("They haven't finished their profile.")
            )}
          </Section>

          <Section title="Uploaded resume">
            {d.profile?.resume ? (
              <>
                <dl className="m-0">
                  <Row label="File" value={d.profile.resume.filename} />
                  <Row label="Uploaded" value={when(d.profile.resume.uploaded_at)} />
                  <Row label="Skills read" value={d.profile.resume.skills.join(", ")} />
                </dl>
                <Button size="sm" className="mt-3" onClick={downloadUploaded} busy={fetchingFile} data-testid="download-uploaded">
                  {fetchingFile ? "Getting the file…" : "Download their resume"}
                </Button>
                {fileError && (
                  <div className="mt-3">
                    <ErrorNote>{fileError}</ErrorNote>
                  </div>
                )}
              </>
            ) : (
              nothing("No resume uploaded.")
            )}
          </Section>

          <Section title="Applications" count={d.applications.length}>
            {d.applications.length ? (
              <ul className="space-y-4">
                {d.applications.map((a) => (
                  <li key={a.id} data-testid="person-application" className="border-t border-line pt-3 first:border-0 first:pt-0">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <p className="min-w-0 break-words text-[15px] font-medium">
                        {a.posting.title} <span className="font-normal text-muted">at {a.posting.company.name}</span>
                      </p>
                      <StatusPill status={a.status} />
                    </div>
                    <div className="mt-2">
                      <Timeline events={a.events} status={a.status} />
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              nothing("No applications tracked.")
            )}
          </Section>

          <Section title="Saved postings" count={d.saved.length}>
            {d.saved.length ? (
              <ul className="space-y-1.5 text-sm">
                {d.saved.map((p) => (
                  <li key={p.id} className="break-words" data-testid="person-saved">
                    <a href={p.url} target="_blank" rel="noreferrer" className="text-accent-text underline underline-offset-2">
                      {p.title}
                    </a>{" "}
                    <span className="text-muted">at {p.company.name}</span>
                  </li>
                ))}
              </ul>
            ) : (
              nothing("Nothing saved.")
            )}
          </Section>

          <Section title="Tailored resumes" count={d.resumes.length}>
            {d.resumes.length ? (
              <ul className="space-y-1.5 text-sm">
                {d.resumes.map((r) => (
                  <li key={r.id} className="break-words" data-testid="person-resume">
                    <span className="font-medium">{r.name}</span>
                    <span className="text-muted">
                      {r.posting ? ` for ${r.posting.title} at ${r.posting.company}` : " for a pasted job description"}
                      {` · updated ${when(r.updated_at)}`}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              nothing("No tailored resumes.")
            )}
          </Section>

          <Section title="Reviews" count={d.reviews.length}>
            {d.reviews.length ? (
              <ul className="space-y-3">
                {d.reviews.map((r) => (
                  <li key={r.id} data-testid="person-review">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <Stars rating={r.rating} />
                      <time dateTime={r.created_at} className="font-mono text-[13px] text-faint">
                        {when(r.created_at)}
                      </time>
                    </div>
                    <p className="mt-1.5 whitespace-pre-wrap break-words text-[15px]">{r.body}</p>
                  </li>
                ))}
              </ul>
            ) : (
              nothing("No reviews.")
            )}
          </Section>
        </div>
      )}
    </AppShell>
  );
}

export default function AdminUserPage() {
  return (
    <Suspense>
      <UserDetail />
    </Suspense>
  );
}
