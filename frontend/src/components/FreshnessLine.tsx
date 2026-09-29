"use client";
// One quiet line saying how fresh the listings are. It is informational:
// if the status can't be fetched it renders nothing and the dashboard
// carries on.
import { useEffect, useState } from "react";
import { getIngestStatus } from "@/lib/api";
import { describeFreshness, freshnessDetail, type FreshnessTone } from "@/lib/freshness";
import type { IngestStatus } from "@/lib/types";

const RECHECK_WHILE_RUNNING_MS = 20_000;

const TONE: Record<FreshnessTone, { text: string; dot: string }> = {
  quiet: { text: "text-faint", dot: "" },
  busy: { text: "text-muted", dot: "bg-accent animate-pulse" },
  // Noticeable, but a note rather than an alarm: amber, no fill, no icon.
  warn: { text: "text-warn", dot: "bg-warn" },
};

export function FreshnessLine() {
  const [seen, setSeen] = useState<{ status: IngestStatus; at: number } | null>(null);
  const running = seen?.status.running ?? false;
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getIngestStatus()
      .then((status) => !cancelled && setSeen({ status, at: Date.now() }))
      .catch(() => !cancelled && setSeen(null));
    return () => {
      cancelled = true;
    };
  }, [tick]);

  // While a refresh is in progress, look again now and then so the line
  // doesn't say "updating" forever.
  useEffect(() => {
    if (!running) return;
    const t = setTimeout(() => setTick((n) => n + 1), RECHECK_WHILE_RUNNING_MS);
    return () => clearTimeout(t);
  }, [running, seen]);

  if (!seen) return null;
  const { tone, text } = describeFreshness(seen.status, seen.at);
  const style = TONE[tone];

  return (
    <p
      data-testid="freshness"
      data-tone={tone}
      role={tone === "warn" ? "status" : undefined}
      title={freshnessDetail(seen.status)}
      className={`mt-0.5 flex items-baseline gap-1.5 text-[13px] leading-5 ${style.text}`}
    >
      {style.dot && <span aria-hidden className={`relative top-[-1px] h-1.5 w-1.5 shrink-0 rounded-full ${style.dot}`} />}
      <span className="min-w-0">{text}</span>
    </p>
  );
}
