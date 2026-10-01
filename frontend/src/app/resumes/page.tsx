"use client";
// "Saved resumes": every tailored resume, newest change first.
import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { deleteResume, listResumes, updateResume } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { longDate } from "@/lib/format";
import type { ResumeSummary } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { Dialog } from "@/components/Dialog";
import { DownloadButtons } from "@/components/resume/DownloadButtons";
import { NAME_MAX } from "@/components/resume/TailoredEditor";
import { Button, ErrorNote, Spinner } from "@/components/ui";

function Rename({ resume, onDone }: { resume: ResumeSummary; onDone: (r: ResumeSummary | null) => void }) {
  const [name, setName] = useState(resume.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const trimmed = name.trim();
  const problem = !trimmed ? "Give it a name." : trimmed.length > NAME_MAX ? `At most ${NAME_MAX} characters.` : null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (problem) return;
    if (trimmed === resume.name) return onDone(null);
    setBusy(true);
    setError(null);
    try {
      const saved = await updateResume(resume.id, { name: trimmed });
      onDone({ ...resume, name: saved.name, updated_at: saved.updated_at });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't rename it.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-1.5" noValidate>
      <label className="block">
        <span className="sr-only">New name for {resume.name}</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
          onKeyDown={(e) => e.key === "Escape" && onDone(null)}
          aria-invalid={problem ? true : undefined}
          data-testid="rename-input"
          className="h-10 w-full rounded-control border border-line-strong bg-surface px-3 text-[15px]"
        />
      </label>
      {problem && <p className="text-sm text-danger">{problem}</p>}
      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="flex gap-2">
        <Button type="submit" size="sm" variant="primary" busy={busy} disabled={!!problem} data-testid="rename-save">
          Save name
        </Button>
        <Button size="sm" onClick={() => onDone(null)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

export default function ResumesPage() {
  const authed = useRequireAuth();
  const [items, setItems] = useState<ResumeSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<ResumeSummary | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    if (!authed) return;
    let cancelled = false;
    listResumes()
      .then((list) => !cancelled && setItems(list))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : "Couldn't load your resumes."));
    return () => {
      cancelled = true;
    };
  }, [authed]);

  async function confirmDelete() {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await deleteResume(deleting.id);
      setItems((list) => list && list.filter((r) => r.id !== deleting.id));
      setDeleting(null);
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : "Couldn't delete it.");
    } finally {
      setDeleteBusy(false);
    }
  }

  if (!authed) return null;

  return (
    <AppShell>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-xl font-semibold tracking-tight">Saved resumes</h1>
        <div className="flex gap-4 text-sm">
          <Link href="/resume" className="font-medium text-accent-text underline underline-offset-2">
            Base resume
          </Link>
          <Link href="/tailor" className="font-medium text-accent-text underline underline-offset-2">
            Tailor for a pasted job
          </Link>
        </div>
      </div>

      {error && (
        <div className="mt-3">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}

      {!items ? (
        !error && (
          <div className="mt-4">
            <Spinner label="Loading your resumes" />
          </div>
        )
      ) : items.length === 0 ? (
        <div className="mt-4 rounded-card border border-dashed border-line-strong p-6 text-center" data-testid="resumes-empty">
          <p className="font-medium">No saved resumes yet.</p>
          <p className="mt-1 text-sm text-muted">
            Use Tailor resume on a posting in{" "}
            <Link href="/" className="font-medium text-accent-text underline underline-offset-2">
              your matches
            </Link>
            , then save the draft.
          </p>
        </div>
      ) : (
        <ul className="mt-4 space-y-3" aria-label="Saved resumes">
          {items.map((r) => (
            <li key={r.id} data-testid="saved-resume" className="rounded-card border border-line bg-surface p-3.5 sm:p-4">
              {renaming === r.id ? (
                <Rename
                  resume={r}
                  onDone={(changed) => {
                    if (changed) setItems((list) => list && list.map((x) => (x.id === r.id ? changed : x)));
                    setRenaming(null);
                  }}
                />
              ) : (
                <>
                  <h2 className="break-words text-[15px] font-semibold" data-testid="saved-resume-name">
                    {r.name}
                  </h2>
                  <p className="break-words text-sm text-muted">
                    {r.posting ? `For ${r.posting.title} at ${r.posting.company}` : "For a pasted job description"}
                  </p>
                  <p className="font-mono text-[13px] text-faint">Updated {longDate(r.updated_at)}</p>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Link
                      href={`/resumes/edit?id=${r.id}`}
                      className="inline-flex h-9 items-center rounded-control border border-line-strong bg-surface px-3 text-sm font-medium hover:bg-surface-2"
                      aria-label={`Open ${r.name}`}
                    >
                      Open
                    </Link>
                    <Button size="sm" onClick={() => setRenaming(r.id)} aria-label={`Rename ${r.name}`} data-testid="rename">
                      Rename
                    </Button>
                    <DownloadButtons prepare={async () => r.id} name={r.name} />
                    <Button size="sm" variant="danger" onClick={() => setDeleting(r)} aria-label={`Delete ${r.name}`} data-testid="delete-resume">
                      Delete
                    </Button>
                  </div>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      <Dialog open={!!deleting} onClose={() => setDeleting(null)} title="Delete this resume?">
        {deleting && (
          <div className="space-y-4">
            <p className="text-sm">
              <span className="font-medium">{deleting.name}</span> will be deleted for good. Your base resume and your
              other saved resumes are not affected.
            </p>
            {deleteError && <ErrorNote>{deleteError}</ErrorNote>}
            <div className="flex justify-end gap-2">
              <Button onClick={() => setDeleting(null)} disabled={deleteBusy}>
                Keep it
              </Button>
              <Button variant="danger" onClick={confirmDelete} busy={deleteBusy} data-testid="confirm-delete-resume">
                {deleteBusy ? "Deleting…" : "Delete resume"}
              </Button>
            </div>
          </div>
        )}
      </Dialog>
    </AppShell>
  );
}
