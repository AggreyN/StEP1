"use client";
// A tailored resume being edited: its name, the editor, Save, and the two
// downloads. Used straight after tailoring (not saved yet) and when opening
// a saved one.
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { createResume, updateResume } from "@/lib/api";
import type { ResumeDoc } from "@/lib/types";
import { Button, ErrorNote } from "../ui";
import { DownloadButtons } from "./DownloadButtons";
import { ResumeEditor, resumeProblem, tidy } from "./ResumeEditor";

export const NAME_MAX = 80;

export function TailoredEditor({
  initial,
}: {
  initial: { id: number | null; name: string; doc: ResumeDoc; postingId?: string };
}) {
  const [id, setId] = useState<number | null>(initial.id);
  const [name, setName] = useState(initial.name.slice(0, NAME_MAX));
  const [doc, setDoc] = useState<ResumeDoc>(initial.doc);
  const [dirty, setDirty] = useState(initial.id === null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justSaved, setJustSaved] = useState(false);
  const saving = useRef<Promise<number | null> | null>(null);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const trimmed = name.trim();
  const nameProblem = !trimmed ? "Give it a name." : trimmed.length > NAME_MAX ? `A name can be at most ${NAME_MAX} characters.` : null;

  /** Saves if needed. Resolves to the saved id, or null if it couldn't. */
  function save(): Promise<number | null> {
    if (!dirty && id !== null) return Promise.resolve(id);
    if (saving.current) return saving.current;
    const clean = tidy(doc);
    const problem = nameProblem ?? resumeProblem(clean);
    if (problem) {
      setError(problem);
      return Promise.resolve(null);
    }
    setBusy(true);
    setError(null);
    saving.current = (async () => {
      try {
        const saved =
          id === null
            ? await createResume({ name: trimmed, doc: clean, ...(initial.postingId ? { posting_id: initial.postingId } : {}) })
            : await updateResume(id, { name: trimmed, doc: clean });
        setId(saved.id);
        setDoc(saved.doc ?? clean);
        setDirty(false);
        setJustSaved(true);
        return saved.id;
      } catch (e) {
        setError(e instanceof Error ? e.message : "Couldn't save.");
        return null;
      } finally {
        setBusy(false);
        saving.current = null;
      }
    })();
    return saving.current;
  }

  return (
    <div className="space-y-4">
      <div className="rounded-card border border-line bg-surface p-3.5 sm:p-5">
        <label className="block">
          <span className="mb-1 block text-sm font-medium">Name for this resume</span>
          <input
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setDirty(true);
              setJustSaved(false);
            }}
            aria-invalid={nameProblem ? true : undefined}
            aria-describedby="resume-name-hint"
            data-testid="resume-name"
            className="h-11 w-full rounded-control border border-line-strong bg-surface px-3 text-[15px]"
          />
          <span id="resume-name-hint" className={`mt-1 block font-mono text-[12px] ${nameProblem ? "text-danger" : "text-faint"}`}>
            {nameProblem ?? `${trimmed.length} of ${NAME_MAX} characters. Only you see this name.`}
          </span>
        </label>
      </div>

      <ResumeEditor
        value={doc}
        onChange={(v) => {
          setDoc(v);
          setDirty(true);
          setJustSaved(false);
        }}
      />

      <div className="sticky bottom-14 z-10 -mx-4 space-y-2 border-t border-line bg-bg/95 px-4 py-3 backdrop-blur sm:bottom-0">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted" role="status" data-testid="tailored-status">
            {dirty ? (id === null ? "Not saved yet." : "Unsaved changes.") : justSaved ? "Saved." : "Up to date."}
            {!dirty && id !== null && (
              <>
                {" "}
                <Link href="/resumes" className="font-medium text-accent-text underline underline-offset-2">
                  Saved resumes
                </Link>
              </>
            )}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <DownloadButtons prepare={save} name={trimmed || "resume"} disabled={busy} />
            <Button variant="primary" onClick={() => void save()} busy={busy} disabled={!dirty || !!nameProblem} data-testid="save-tailored">
              {busy ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
        {error && <ErrorNote>{error}</ErrorNote>}
      </div>
    </div>
  );
}
