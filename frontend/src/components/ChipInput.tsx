"use client";
// Free-text chips (preferred locations). Enter or the Add button adds one;
// the button on a chip removes it. A comma does not add, because places
// have commas in them ("Washington, DC").
import { useRef, useState } from "react";
import { XIcon } from "./icons";

export function ChipInput({
  value,
  onChange,
  placeholder,
  label,
  max,
  maxLength,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  label: string;
  /** most entries allowed */
  max: number;
  /** longest entry allowed, in characters */
  maxLength: number;
}) {
  const [draft, setDraft] = useState("");
  const field = useRef<HTMLInputElement>(null);
  const entry = draft.trim().replace(/,$/, "").trim();
  const full = value.length >= max;
  const problem = full
    ? `That's the most you can add (${max}). Remove one to add another.`
    : entry.length > maxLength
      ? `Each one can be at most ${maxLength} characters (this is ${entry.length}).`
      : null;
  const hintId = `${label.replace(/\W+/g, "-").toLowerCase()}-hint`;

  const add = () => {
    if (!entry || problem) return;
    if (!value.some((x) => x.toLowerCase() === entry.toLowerCase())) onChange([...value, entry]);
    setDraft("");
    field.current?.focus(); // ready for the next one; the Add button is about to disable
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
                onClick={() => {
                  onChange(value.filter((x) => x !== v));
                  field.current?.focus(); // the button that had focus is gone
                }}
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
          ref={field}
          aria-label={label}
          value={draft}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          aria-invalid={problem && entry ? true : undefined}
          aria-describedby={problem ? hintId : undefined}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          className="h-11 min-w-0 flex-1 rounded-control border border-line-strong bg-surface px-3 text-[15px] placeholder:text-faint"
        />
        <button
          type="button"
          onClick={add}
          disabled={!entry || !!problem}
          className="h-11 shrink-0 rounded-control border border-line-strong bg-surface px-4 text-sm font-medium hover:bg-surface-2 disabled:opacity-45"
        >
          Add
        </button>
      </div>
      {problem && (full || entry) && (
        <p id={hintId} role="status" className={`mt-1.5 text-sm ${full && !entry ? "text-muted" : "text-danger"}`}>
          {problem}
        </p>
      )}
    </div>
  );
}
