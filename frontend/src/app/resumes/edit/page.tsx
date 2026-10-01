"use client";
// One saved resume, open for editing: /resumes/edit?id=12.
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ApiError, getResume } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { ResumeFull } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { TailoredEditor } from "@/components/resume/TailoredEditor";
import { ErrorNote, Spinner } from "@/components/ui";

function EditResume() {
  const authed = useRequireAuth();
  const id = useSearchParams().get("id") ?? "";
  const [loaded, setLoaded] = useState<{ id: string; resume: ResumeFull } | null>(null);
  const [failure, setFailure] = useState<{ id: string; message: string } | null>(null);

  useEffect(() => {
    if (!authed || !id) return;
    let cancelled = false;
    getResume(id)
      .then((resume) => !cancelled && setLoaded({ id, resume }))
      .catch(
        (e: unknown) =>
          !cancelled &&
          setFailure({
            id,
            message: e instanceof ApiError && e.status === 404 ? "There is no saved resume here." : e instanceof Error ? e.message : "Couldn't open it.",
          })
      );
    return () => {
      cancelled = true;
    };
  }, [authed, id]);

  if (!authed) return null;
  const resume = loaded?.id === id ? loaded.resume : null;
  const error = !id ? "This link doesn't say which resume to open." : failure?.id === id ? failure.message : null;

  return (
    <AppShell>
      <Link href="/resumes" className="mb-3 inline-block text-sm text-muted hover:text-fg">
        ← Saved resumes
      </Link>
      <h1 className="break-words text-xl font-semibold tracking-tight">{resume ? resume.name : "Saved resume"}</h1>
      {resume?.posting && (
        <p className="text-sm text-muted">
          For {resume.posting.title} at {resume.posting.company}
        </p>
      )}
      <div className="mt-4">
        {error ? (
          <ErrorNote>{error}</ErrorNote>
        ) : !resume ? (
          <Spinner label="Opening" />
        ) : (
          <TailoredEditor
            key={resume.id}
            initial={{ id: resume.id, name: resume.name, doc: resume.doc, postingId: resume.posting?.id }}
          />
        )}
      </div>
    </AppShell>
  );
}

export default function EditResumePage() {
  return (
    <Suspense>
      <EditResume />
    </Suspense>
  );
}
