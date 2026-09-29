"use client";
// Free-text chips (preferred locations). Enter or comma adds; × removes.
import { useState } from "react";
import { XIcon } from "./icons";

export function ChipInput({
  value,
  onChange,
  placeholder,
  label,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  label: string;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const v = draft.trim().replace(/,$/, "").trim();
    if (v && !value.some((x) => x.toLowerCase() === v.toLowerCase())) onChange([...value, v]);
    setDraft("");
  };
  return (
    <div>
      {value.length > 0 && (
        <ul className="mb-2 flex flex-wrap gap-2" aria-label={label}>
          {value.map((v) => (
            <li key={v} className="inline-flex items-center gap-1 rounded-chip bg-surface-2 py-1 pl-2.5 pr-1 text-sm">
              {v}
              <button
                type="button"
                onClick={() => onChange(value.filter((x) => x !== v))}
                aria-label={`Remove ${v}`}
                className="inline-flex h-7 w-7 items-center justify-center rounded-chip text-muted hover:bg-surface hover:text-fg"
              >
                <XIcon />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <input
          aria-label={label}
          value={draft}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              add();
            }
          }}
          className="h-11 min-w-0 flex-1 rounded-control border border-line-strong bg-surface px-3 text-[15px] placeholder:text-faint focus:border-accent focus:outline-none"
        />
        <button
          type="button"
          onClick={add}
          disabled={!draft.trim()}
          className="h-11 shrink-0 rounded-control border border-line-strong bg-surface px-4 text-sm font-medium hover:bg-surface-2 disabled:opacity-45"
        >
          Add
        </button>
      </div>
    </div>
  );
}
