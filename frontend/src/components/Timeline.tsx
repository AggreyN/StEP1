// Vertical stepper over the application's event log. Purely presentational:
// it renders the events the API returned, in order, and marks the one that
// matches the API's current `status`.
import { longDate } from "@/lib/format";
import { kindLabel, statusTone } from "@/lib/labels";
import type { ApplicationEvent } from "@/lib/types";

function dotClass(kind: string, current: boolean): string {
  if (kind === "note" || kind === "outreach_sent") return "h-2.5 w-2.5 border border-line-strong bg-surface";
  const tone = statusTone(kind);
  if (tone === "quiet") return "h-3.5 w-3.5 border-2 border-dashed border-faint bg-surface";
  if (tone === "negative") return "h-3.5 w-3.5 bg-danger";
  if (tone === "positive") return "h-3.5 w-3.5 bg-positive";
  if (current) return "h-3.5 w-3.5 bg-accent ring-4 ring-accent-soft";
  return "h-3.5 w-3.5 bg-line-strong";
}

export function Timeline({ events, status }: { events: ApplicationEvent[]; status: string }) {
  let currentIdx = -1;
  events.forEach((e, i) => {
    if (e.kind === status) currentIdx = i;
  });

  return (
    <ol className="relative" data-testid="timeline">
      {events.map((e, i) => {
        const current = i === currentIdx;
        const quiet = statusTone(e.kind) === "quiet";
        const minor = e.kind === "note" || e.kind === "outreach_sent";
        const last = i === events.length - 1;
        return (
          <li
            key={e.id}
            data-testid="timeline-event"
            data-kind={e.kind}
            aria-current={current ? "step" : undefined}
            className="relative flex gap-3 pb-5 last:pb-0"
          >
            <div className="relative flex w-4 shrink-0 justify-center">
              {!last && <span aria-hidden className="absolute bottom-[-1.25rem] top-5 w-px bg-line" />}
              <span aria-hidden className={`relative mt-1 rounded-full ${dotClass(e.kind, current)}`} />
            </div>
            <div className={`min-w-0 flex-1 ${quiet ? "text-faint" : ""}`}>
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span
                  className={`${minor ? "text-sm text-muted" : "text-[15px]"} ${
                    current ? "font-semibold" : minor ? "" : "font-medium"
                  } ${quiet ? "italic" : ""}`}
                >
                  {kindLabel(e.kind)}
                </span>
                {current && (
                  <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide text-muted">
                    Current
                  </span>
                )}
                <time dateTime={e.occurred_at} className="tnum text-sm text-faint">
                  {longDate(e.occurred_at)}
                </time>
              </div>
              {e.kind === "ghosted" && (
                <p className="mt-0.5 text-sm">No response after 30 days. Logged automatically — nothing you did.</p>
              )}
              {e.note && (
                <p className={`mt-1 whitespace-pre-wrap break-words text-sm ${quiet ? "" : "text-muted"}`}>{e.note}</p>
              )}
              {e.source !== "manual" && e.kind !== "ghosted" && (
                <p className="mt-0.5 text-xs text-faint">Added automatically</p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
