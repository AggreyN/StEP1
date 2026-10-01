"use client";
// "Your base resume": the one every tailored resume is built from.
import { useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, extractBaseResume, getBaseResume, getProfile, saveBaseResume } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { BaseResume } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { ResumeEditor, resumeProblem, tidy } from "@/components/resume/ResumeEditor";
import { Button, ErrorNote, Spinner } from "@/components/ui";

type Loaded = { base: BaseResume | null; hasUpload: boolean };

export default function BaseResumePage() {
  const authed = useRequireAuth();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [draft, setDraft] = useState<BaseResume | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<"extract" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    if (!authed) return;
    let cancelled = false;
    Promise.all([getBaseResume(), getProfile()])
      .then(([base, profile]) => {
        if (cancelled) return;
        setLoaded({ base, hasUpload: !!profile?.resume });
        if (base) setDraft(base);
      })
      .catch((e: unknown) => !cancelled && setLoadError(e instanceof Error ? e.message : "Couldn't load your resume."));
    return () => {
      cancelled = true;
    };
  }, [authed]);

  // Leaving with unsaved changes asks first.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  async function extract() {
    setBusy("extract");
    setError(null);
    try {
      setDraft(await extractBaseResume());
      setDirty(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't read your resume.");
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    if (!draft) return;
    const clean = tidy(draft);
    const problem = resumeProblem(clean);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy("save");
    setError(null);
    try {
      const saved = await saveBaseResume(clean);
      setDraft(saved ?? clean);
      setLoaded((l) => l && { ...l, base: saved ?? clean });
      setDirty(false);
      setSavedAt(Date.now());
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : "Couldn't save.");
    } finally {
      setBusy(null);
    }
  }

  if (!authed) return null;

  return (
    <AppShell>
      <h1 className="text-xl font-semibold tracking-tight">Your base resume</h1>
      <p className="mt-1 max-w-prose text-sm text-muted">
        Every tailored resume is built from this one. Keep it complete and accurate: tailoring chooses and rewords
        what is here, and never adds experience you don&apos;t have.
      </p>

      {loadError ? (
        <div className="mt-4">
          <ErrorNote>{loadError}</ErrorNote>
        </div>
      ) : !loaded ? (
        <div className="mt-4">
          <Spinner label="Loading your resume" />
        </div>
      ) : !draft ? (
        <div className="mt-4 rounded-card border border-line bg-surface p-4 sm:p-5" data-testid="base-empty">
          <h2 className="text-base font-semibold">You don&apos;t have a base resume yet</h2>
          {loaded.hasUpload ? (
            <>
              <p className="mt-1 text-sm text-muted">
                StEP1 can make a first draft from the resume you uploaded. Check it over, fix anything it got wrong,
                then save.
              </p>
              <Button variant="primary" className="mt-4" onClick={extract} busy={busy === "extract"} data-testid="extract-base">
                {busy === "extract" ? "Reading your resume…" : "Build it from my uploaded resume"}
              </Button>
            </>
          ) : (
            <p className="mt-1 text-sm text-muted" data-testid="needs-upload">
              First upload your resume on your{" "}
              <Link href="/onboarding" className="font-medium text-accent-text underline underline-offset-2">
                Profile
              </Link>
              . StEP1 makes the first draft from it.
            </p>
          )}
          {error && (
            <div className="mt-3">
              <ErrorNote>{error}</ErrorNote>
            </div>
          )}
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          <ResumeEditor
            value={draft}
            withSkills
            onChange={(v) => {
              setDraft(v);
              setDirty(true);
            }}
          />
          <div className="sticky bottom-14 z-10 -mx-4 flex flex-wrap items-center justify-between gap-3 border-t border-line bg-bg/95 px-4 py-3 backdrop-blur sm:bottom-0">
            <p className="text-sm text-muted" role="status" data-testid="base-status">
              {dirty ? "Unsaved changes." : savedAt ? "Saved." : loaded.base ? "Up to date." : ""}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              {loaded.base && !dirty && (
                <Link href="/tailor" className="text-sm font-medium text-accent-text underline underline-offset-2">
                  Tailor a resume
                </Link>
              )}
              <Button variant="primary" onClick={save} busy={busy === "save"} disabled={!dirty} data-testid="save-base">
                {busy === "save" ? "Saving…" : "Save base resume"}
              </Button>
            </div>
          </div>
          {error && <ErrorNote>{error}</ErrorNote>}
        </div>
      )}
    </AppShell>
  );
}
