"use client";
// Tailor a resume: for a posting (/tailor?posting=<id>) or for a pasted job
// description. Tailoring takes 10 to 40 seconds; the page says so and shows
// how long it has been, rather than a made-up percentage.
import { Suspense, useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ApiError, getPosting, tailorResume } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { Posting, TailorResult } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { TailoredEditor } from "@/components/resume/TailoredEditor";
import { Button, ErrorNote, Spinner } from "@/components/ui";

const JOB_TEXT_MAX = 20000;

type Ask = { posting_id: string } | { job_text: string };

function Report({ result }: { result: TailorResult }) {
  const r = result.report;
  return (
    <section className="rounded-card border border-line bg-surface p-3.5 sm:p-5" aria-labelledby="report-heading" data-testid="tailor-report">
      <h2 id="report-heading" className="text-base font-semibold">
        What was done
      </h2>
      <h3 className="mt-3 text-sm font-semibold">How well it fits</h3>
      <p className="mt-0.5 whitespace-pre-wrap text-[15px]" data-testid="report-fit">
        {r.fit}
      </p>
      {r.changes.length > 0 && (
        <>
          <h3 className="mt-3 text-sm font-semibold">What changed</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-[15px]" data-testid="report-changes">
            {r.changes.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </>
      )}
      {r.gaps.length > 0 && (
        <>
          <h3 className="mt-3 text-sm font-semibold">Gaps the job asks for</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-[15px]" data-testid="report-gaps">
            {r.gaps.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        </>
      )}
      {r.question && (
        <div className="mt-3 rounded-control bg-accent-soft px-3 py-2 text-[15px] text-accent-text" data-testid="report-question">
          <p className="font-semibold">A question for you</p>
          <p className="mt-0.5">{r.question}</p>
          <p className="mt-1 text-sm">If the answer is yes, add it to your base resume and tailor again.</p>
        </div>
      )}
      <p className="mt-3 text-sm text-muted">Read the draft below before you send it anywhere. It is yours to change.</p>
    </section>
  );
}

function Tailor() {
  const authed = useRequireAuth();
  const postingId = useSearchParams().get("posting");
  const [posting, setPosting] = useState<Posting | null>(null);
  const [jobText, setJobText] = useState("");
  const [running, setRunning] = useState<{ startedAt: number } | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState<{ result: TailorResult; postingId?: string } | null>(null);
  const [problem, setProblem] = useState<{ message: string; needsBase: boolean } | null>(null);
  const started = useRef<string | null>(null);

  const run = useCallback(async (ask: Ask) => {
    setRunning({ startedAt: Date.now() });
    setElapsed(0);
    setProblem(null);
    setResult(null);
    try {
      const out = await tailorResume(ask);
      setResult({ result: out, postingId: "posting_id" in ask ? ask.posting_id : undefined });
    } catch (e) {
      setProblem({
        message: e instanceof Error ? e.message : "Couldn't tailor your resume.",
        needsBase: e instanceof ApiError && e.status === 409,
      });
    } finally {
      setRunning(null);
    }
  }, []);

  // From a posting: look it up for the heading, and start straight away (once).
  useEffect(() => {
    if (!authed || !postingId || started.current === postingId) return;
    started.current = postingId;
    getPosting(postingId)
      .then(setPosting)
      .catch(() => {});
    void run({ posting_id: postingId });
  }, [authed, postingId, run]);

  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - running.startedAt) / 1000)), 1000);
    return () => clearInterval(t);
  }, [running]);

  const length = jobText.trim().length;
  const tooLong = jobText.length > JOB_TEXT_MAX;

  function submitText(e: FormEvent) {
    e.preventDefault();
    if (!length || tooLong || running) return;
    void run({ job_text: jobText });
  }

  if (!authed) return null;

  const forWhat = postingId
    ? posting
      ? `${posting.title} at ${posting.company.name}`
      : "this posting"
    : "the job you pasted";

  return (
    <AppShell>
      <h1 className="text-xl font-semibold tracking-tight">Tailor your resume</h1>
      <p className="mt-1 max-w-prose text-sm text-muted">
        A draft of your base resume, reworked for one job. It only uses what is in your{" "}
        <Link href="/resume" className="font-medium text-accent-text underline underline-offset-2">
          base resume
        </Link>
        .
      </p>

      {!postingId && !result && (
        <form onSubmit={submitText} noValidate className="mt-4 rounded-card border border-line bg-surface p-3.5 sm:p-5">
          <label className="block">
            <span className="mb-1 block text-sm font-medium">Job description</span>
            <span className="mb-1.5 block text-sm text-muted" id="job-text-hint">
              Paste the whole posting: the role, what they ask for, and what they offer. To tailor for a posting
              in your matches, use its Tailor resume button instead.
            </span>
            <textarea
              value={jobText}
              onChange={(e) => setJobText(e.target.value)}
              rows={10}
              aria-describedby="job-text-hint job-text-count"
              aria-invalid={tooLong ? true : undefined}
              data-testid="job-text"
              className="w-full rounded-control border border-line-strong bg-surface px-3 py-2 text-[15px]"
            />
            <span id="job-text-count" className={`mt-1 block font-mono text-[12px] ${tooLong ? "text-danger" : "text-faint"}`}>
              {jobText.length.toLocaleString()} of {JOB_TEXT_MAX.toLocaleString()} characters
              {tooLong ? `. That is ${(jobText.length - JOB_TEXT_MAX).toLocaleString()} too many.` : ""}
            </span>
          </label>
          <Button type="submit" variant="primary" className="mt-3" disabled={!length || tooLong} busy={!!running} data-testid="tailor-text">
            Tailor my resume
          </Button>
        </form>
      )}

      {running && (
        <div className="mt-4 rounded-card border border-line bg-surface p-4" role="status" aria-live="polite" data-testid="tailoring">
          <Spinner label={`Tailoring your resume for ${forWhat}`} />
          <p className="mt-2 text-sm text-muted">
            This usually takes 10 to 40 seconds and can take up to a minute. Keep this page open.
          </p>
          <p className="mt-1 font-mono text-[13px] text-faint" aria-hidden>
            {elapsed}s so far
          </p>
        </div>
      )}

      {problem && (
        <div className="mt-4 space-y-3" data-testid="tailor-problem">
          <ErrorNote>{problem.message}</ErrorNote>
          {problem.needsBase ? (
            <Link href="/resume" className="inline-block font-medium text-accent-text underline underline-offset-2">
              Set up your base resume
            </Link>
          ) : (
            <Button
              onClick={() => void run(postingId ? { posting_id: postingId } : { job_text: jobText })}
              data-testid="tailor-again"
            >
              Try again
            </Button>
          )}
        </div>
      )}

      {result && (
        <div className="mt-4 space-y-4">
          <Report result={result.result} />
          <h2 className="text-lg font-semibold tracking-tight">Your draft for {forWhat}</h2>
          <TailoredEditor
            initial={{
              id: null,
              name: result.result.suggested_name,
              doc: result.result.draft,
              postingId: result.postingId,
            }}
          />
        </div>
      )}
    </AppShell>
  );
}

export default function TailorPage() {
  return (
    <Suspense>
      <Tailor />
    </Suspense>
  );
}
