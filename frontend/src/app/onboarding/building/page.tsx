"use client";
// "Starting your career…" — polls GET /feed/status on the Retry-After
// interval and renders the real step text. No artificial delay: if the
// first poll says ready, we route straight through.
import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, getFeedStatus } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { FeedStatus } from "@/lib/types";
import { Wordmark } from "@/components/AppShell";
import { SiteFooter } from "@/components/SiteFooter";
import { ErrorNote, ProgressBar } from "@/components/ui";

const SLOW_AFTER_MS = 30_000;

function Building() {
  const authed = useRequireAuth();
  const router = useRouter();
  const params = useSearchParams();
  const initialRetry = Math.max(0.5, Number(params.get("retry")) || 1);

  const [status, setStatus] = useState<FeedStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [slow, setSlow] = useState(false);
  // Set when the API says to slow down (429). Polling stops until the
  // person asks again; nothing is retried behind their back.
  const [limited, setLimited] = useState<{ attempt: number; message: string } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const startedAt = useRef<number>(0);

  useEffect(() => {
    if (!authed) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (!startedAt.current) startedAt.current = Date.now();

    const poll = async (delaySec: number) => {
      try {
        const s = await getFeedStatus();
        if (cancelled) return;
        setError(null);
        setStatus(s);
        if (s.state === "ready") {
          router.replace("/");
          return;
        }
        if (Date.now() - startedAt.current > SLOW_AFTER_MS) setSlow(true);
        timer = setTimeout(() => poll(s.retryAfter ?? delaySec), (s.retryAfter ?? delaySec) * 1000);
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 409) {
          router.replace("/onboarding"); // no profile yet, so nothing is building
          return;
        }
        if (e instanceof ApiError && e.status === 429) {
          setError(null);
          setLimited({ attempt, message: e.message });
          return;
        }
        setError(e instanceof Error ? e.message : "Couldn't check progress.");
        if (Date.now() - startedAt.current > SLOW_AFTER_MS) setSlow(true);
        timer = setTimeout(() => poll(Math.min(delaySec * 2, 10)), Math.min(delaySec * 2, 10) * 1000);
      }
    };
    poll(initialRetry);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [authed, initialRetry, router, attempt]);

  if (!authed) return null;

  const pct = status?.pct ?? 0;
  const paused = limited?.attempt === attempt ? limited.message : null;
  return (
    <div className="flex min-h-screen flex-col">
    <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-4 py-10">
      <Wordmark />
      <h1 className="mt-6 text-2xl font-semibold tracking-tight">Starting your career…</h1>
      <p className="mt-1 text-sm text-muted">We&apos;re ranking every open internship against your profile.</p>

      <div className="mt-8 space-y-3">
        <ProgressBar pct={pct} label="Building your matches" />
        <div className="flex items-baseline justify-between gap-3 text-sm">
          <span data-testid="building-step" className="font-medium" aria-live="polite">
            {status ? status.step : "Connecting…"}
          </span>
          <span className="tnum text-muted">{Math.round(pct)}%</span>
        </div>
      </div>

      {error && !paused && (
        <div className="mt-6">
          <ErrorNote>{error} Retrying…</ErrorNote>
        </div>
      )}

      {paused && (
        <div className="mt-6">
          <ErrorNote onRetry={() => setAttempt((n) => n + 1)}>{paused}</ErrorNote>
        </div>
      )}

      {slow && (
        <div className="mt-8 rounded-card border border-line bg-surface p-4 text-sm" role="status">
          <p className="font-medium">This is taking longer than usual.</p>
          <p className="mt-1 text-muted">
            Your matches will keep building in the background. You can head to the dashboard now and they&apos;ll appear
            as they&apos;re ready.
          </p>
          <Link href="/" className="mt-3 inline-block font-medium text-accent-text underline underline-offset-2">
            Go to the dashboard anyway
          </Link>
        </div>
      )}
    </main>
    <SiteFooter />
    </div>
  );
}

export default function BuildingPage() {
  return (
    <Suspense>
      <Building />
    </Suspense>
  );
}
