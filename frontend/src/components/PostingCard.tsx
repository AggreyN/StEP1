"use client";
import Link from "next/link";
import { formatSalary, postedAge } from "@/lib/format";
import { kindLabel } from "@/lib/labels";
import type { Posting } from "@/lib/types";
import { CheckIcon, ExternalIcon, StarIcon } from "./icons";
import { ScoreBadge } from "./ScoreBadge";
import { Chip } from "./ui";

export function PostingCard({
  posting,
  onToggleSave,
  onApply,
  saving = false,
}: {
  posting: Posting;
  onToggleSave: (p: Posting) => void;
  onApply: (p: Posting) => void;
  saving?: boolean;
}) {
  const p = posting;
  const salary = formatSalary(p.salary);
  const locs = p.locations.slice(0, 2).join(" · ") + (p.locations.length > 2 ? ` +${p.locations.length - 2}` : "");

  return (
    <article
      data-testid="posting-card"
      data-posting-id={p.id}
      className="rounded-xl border border-line bg-surface p-3.5 sm:p-4"
    >
      <div className="flex items-start gap-3">
        <ScoreBadge score={p.score} />
        <div className="min-w-0 flex-1">
          <h3 className="line-clamp-2 break-words text-[15px] font-semibold leading-snug sm:text-base">
            <a href={p.url} target="_blank" rel="noreferrer" className="hover:underline">
              {p.title}
            </a>
          </h3>
          <p className="truncate text-sm text-muted">
            <span className="font-medium text-fg">{p.company.name}</span>
            {" · "}
            {locs}
            {p.is_remote && " · Remote"}
          </p>
        </div>
        <button
          type="button"
          onClick={() => onToggleSave(p)}
          disabled={saving}
          aria-pressed={p.saved}
          aria-label={p.saved ? "Unsave" : "Save"}
          data-testid="save-toggle"
          className={`-mr-1.5 -mt-1.5 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg ${
            p.saved ? "text-accent" : "text-faint hover:bg-surface-2 hover:text-fg"
          }`}
        >
          <StarIcon filled={p.saved} />
        </button>
      </div>

      {/* Below the header the content runs full width on phones and lines up
          under the title from sm up. */}
      <div className="mt-2.5 sm:mt-2 sm:pl-14">
        {p.reasons.length > 0 && (
          <ul className="flex flex-wrap gap-1.5" aria-label="Why this matches">
            {p.reasons.map((r, i) => (
              <li key={`${r.code}-${i}`} className="max-w-full">
                <Chip className="!border-transparent !bg-accent-soft !text-accent-text" title={r.detail ?? undefined}>
                  <span className="truncate font-medium">{r.label}</span>
                  {r.detail && <span className="hidden truncate opacity-80 sm:inline">· {r.detail}</span>}
                </Chip>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-[13px] text-muted">
          {p.role_labels.map((l) => (
            <Chip key={l} tone="outline">
              {l}
            </Chip>
          ))}
          {p.terms.slice(0, 2).map((t) => (
            <span key={t} className="whitespace-nowrap">
              {t}
            </span>
          ))}
          {salary && <span className="tnum whitespace-nowrap">{salary}</span>}
          <span className="whitespace-nowrap text-faint">Posted {postedAge(p.date_posted)}</span>
        </div>

        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          {p.application ? (
            <Link
              href={`/applications/${p.application.id}`}
              data-testid="application-link"
              className="inline-flex h-10 items-center gap-1.5 rounded-lg bg-surface-2 px-3 text-sm font-medium hover:bg-line sm:h-9"
            >
              <CheckIcon className="text-positive" />
              {kindLabel(p.application.status)} · view timeline
            </Link>
          ) : (
            <button
              type="button"
              onClick={() => onApply(p)}
              data-testid="apply-button"
              className="inline-flex h-10 items-center rounded-lg border border-line-strong bg-surface px-3 text-sm font-medium hover:bg-surface-2 sm:h-9"
            >
              I applied
            </button>
          )}
          <a
            href={p.url}
            target="_blank"
            rel="noreferrer"
            className="ml-auto inline-flex h-10 items-center gap-1 rounded-lg px-2 text-sm text-muted hover:text-fg sm:h-9"
          >
            Open posting
            <ExternalIcon />
          </a>
        </div>
      </div>
    </article>
  );
}
