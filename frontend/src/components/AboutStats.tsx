"use client";
// The three numbers on the About page. They come from GET /stats and are
// printed flat: no count-up, no animation. While they load the row keeps its
// place with empty values; if they can't be fetched the row is left out.
import { useEffect, useState } from "react";
import { getStats } from "@/lib/api";
import type { Stats } from "@/lib/types";

const LABELS: { key: keyof Pick<Stats, "active_postings" | "companies" | "role_families">; label: string }[] = [
  { key: "active_postings", label: "Active postings" },
  { key: "companies", label: "Companies" },
  { key: "role_families", label: "Role families" },
];

/** "row": three across, ruled above and below. "stack": one per line, for a
 *  narrow column beside the About headline. */
export function AboutStats({ layout = "row" }: { layout?: "row" | "stack" }) {
  const [state, setState] = useState<{ stats: Stats } | "loading" | "failed">("loading");

  useEffect(() => {
    let cancelled = false;
    getStats()
      .then((stats) => !cancelled && setState({ stats }))
      .catch(() => !cancelled && setState("failed"));
    return () => {
      cancelled = true;
    };
  }, []);

  if (state === "failed") return null;
  const stats = state === "loading" ? null : state.stats;

  return (
    <dl
      data-testid="about-stats"
      aria-busy={stats ? undefined : true}
      className={
        layout === "stack"
          ? "m-0 flex flex-col border-y border-[var(--line)]"
          : "my-7 flex flex-wrap border-y border-[var(--line)]"
      }
    >
      {LABELS.map((s, i) => (
        <div
          key={s.key}
          className={
            layout === "stack"
              ? `flex min-w-0 flex-col-reverse py-4 ${i < LABELS.length - 1 ? "border-b border-[var(--line)]" : ""}`
              : `flex min-w-0 flex-[1_1_150px] flex-col-reverse px-[18px] pb-[15px] pt-4 ${
                  i < LABELS.length - 1 ? "border-r border-[var(--line)]" : ""
                }`
          }
        >
          <dt className="font-ui mt-[5px] block text-[0.72rem] uppercase tracking-[0.06em] text-[var(--ink-3)]">
            {s.label}
          </dt>
          <dd
            data-testid={`stat-${s.key}`}
            className={`m-0 block min-h-[1.2em] font-mono ${layout === "stack" ? "text-[2rem] text-[var(--accent-text)]" : "text-[1.45rem]"} font-medium leading-[1.2] tracking-[-0.02em] tabular-nums`}
          >
            {stats ? stats[s.key].toLocaleString("en-US") : " "}
          </dd>
        </div>
      ))}
    </dl>
  );
}
