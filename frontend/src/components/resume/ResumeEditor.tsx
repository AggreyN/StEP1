"use client";
// The resume editor, shared by the base resume and tailored ones. Every
// part can be added, removed and moved with buttons (no drag), so it all
// works from the keyboard and on a phone. Nothing here saves: the page
// that holds the resume does, so it can say when there are unsaved changes.
import { useId, type ReactNode } from "react";
import type { ResumeDoc, ResumeEntry, ResumeSection } from "@/lib/types";
import { ChipInput } from "../ChipInput";
import { DownIcon, UpIcon, XIcon } from "../icons";

/** Where a line starts to read as too long for a resume. A hint, not a rule. */
export const LIMITS = { name: 80, contact: 120, title: 60, heading: 120, sub: 120, side: 40, line: 220, skill: 40, skills: 80 };

const field =
  "h-10 w-full min-w-0 rounded-control border border-line-strong bg-surface px-3 text-[15px] placeholder:text-faint";

function move<T>(list: T[], i: number, d: -1 | 1): T[] {
  const j = i + d;
  if (j < 0 || j >= list.length) return list;
  const next = [...list];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}

const blankEntry = (): ResumeEntry => ({ heading: "", right: "", sub: "", sub_right: "", lines: [""] });

/** Up, down and remove for one item in a list. `what` names it for screen readers. */
function ItemButtons({
  what,
  index,
  count,
  onMove,
  onRemove,
}: {
  what: string;
  index: number;
  count: number;
  onMove: (d: -1 | 1) => void;
  onRemove: () => void;
}) {
  const btn =
    "inline-flex h-10 w-9 shrink-0 items-center justify-center rounded-chip text-muted hover:bg-surface-2 hover:text-fg aria-disabled:cursor-not-allowed aria-disabled:opacity-30";
  return (
    <div className="flex shrink-0 items-center">
      <button type="button" className={btn} aria-label={`Move ${what} up`} aria-disabled={index === 0} onClick={() => index > 0 && onMove(-1)}>
        <UpIcon />
      </button>
      <button
        type="button"
        className={btn}
        aria-label={`Move ${what} down`}
        aria-disabled={index === count - 1}
        onClick={() => index < count - 1 && onMove(1)}
      >
        <DownIcon />
      </button>
      <button type="button" className={btn} aria-label={`Remove ${what}`} onClick={onRemove}>
        <XIcon />
      </button>
    </div>
  );
}

/** A labelled text field with a quiet character count that warns past `max`. */
function Text({
  label,
  value,
  onChange,
  max,
  placeholder,
  hideLabel = false,
  multiline = false,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  max: number;
  placeholder?: string;
  hideLabel?: boolean;
  multiline?: boolean;
}) {
  const id = useId();
  const n = value.length;
  const over = n > max;
  const showCount = over || n > max * 0.8;
  return (
    <div className="min-w-0 flex-1">
      <label htmlFor={id} className={hideLabel ? "sr-only" : "mb-1 block text-[13px] font-medium text-muted"}>
        {label}
      </label>
      {multiline ? (
        <textarea
          id={id}
          value={value}
          rows={2}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value.replace(/\n/g, " "))}
          aria-describedby={showCount ? `${id}-count` : undefined}
          className={`${field} h-auto min-h-10 py-2 leading-snug`}
        />
      ) : (
        <input
          id={id}
          value={value}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          aria-describedby={showCount ? `${id}-count` : undefined}
          className={field}
        />
      )}
      {showCount && (
        <span id={`${id}-count`} className={`mt-0.5 block font-mono text-[12px] ${over ? "text-warn" : "text-faint"}`}>
          {n} of about {max} characters{over ? ". Long for one line; consider trimming." : ""}
        </span>
      )}
    </div>
  );
}

function AddButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex h-9 items-center rounded-control border border-dashed border-line-strong px-3 text-sm text-muted hover:border-accent hover:text-accent-text"
    >
      + {children}
    </button>
  );
}

function EntryEditor({
  entry,
  label,
  onChange,
}: {
  entry: ResumeEntry;
  label: string;
  onChange: (e: ResumeEntry) => void;
}) {
  const set = (patch: Partial<ResumeEntry>) => onChange({ ...entry, ...patch });
  return (
    <div className="space-y-2">
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_12rem]">
        <Text label={`${label} heading`} value={entry.heading} onChange={(v) => set({ heading: v })} max={LIMITS.heading} placeholder="Company, school or project" />
        <Text label={`${label} right`} value={entry.right} onChange={(v) => set({ right: v })} max={LIMITS.side} placeholder="Dates" />
        <Text label={`${label} subheading`} value={entry.sub} onChange={(v) => set({ sub: v })} max={LIMITS.sub} placeholder="Role, degree or tools" />
        <Text label={`${label} sub right`} value={entry.sub_right} onChange={(v) => set({ sub_right: v })} max={LIMITS.side} placeholder="Place" />
      </div>
      <fieldset>
        <legend className="mb-1 text-[13px] font-medium text-muted">{label} bullets</legend>
        <ol className="space-y-1.5">
          {entry.lines.map((line, i) => (
            <li key={i} className="flex items-start gap-1" data-testid="resume-line">
              <span aria-hidden className="mt-2.5 w-4 shrink-0 text-center text-faint">
                •
              </span>
              <Text
                hideLabel
                multiline
                label={`${label} bullet ${i + 1}`}
                value={line}
                onChange={(v) => set({ lines: entry.lines.map((l, k) => (k === i ? v : l)) })}
                max={LIMITS.line}
              />
              <ItemButtons
                what={`${label} bullet ${i + 1}`}
                index={i}
                count={entry.lines.length}
                onMove={(d) => set({ lines: move(entry.lines, i, d) })}
                onRemove={() => set({ lines: entry.lines.filter((_, k) => k !== i) })}
              />
            </li>
          ))}
        </ol>
        <div className="mt-2">
          <AddButton onClick={() => set({ lines: [...entry.lines, ""] })}>Add bullet</AddButton>
        </div>
      </fieldset>
    </div>
  );
}

function SectionEditor({
  section,
  n,
  onChange,
}: {
  section: ResumeSection;
  n: number;
  onChange: (s: ResumeSection) => void;
}) {
  const label = section.title.trim() || `Section ${n}`;
  return (
    <div className="space-y-3">
      <Text label={`Section ${n} title`} value={section.title} onChange={(v) => onChange({ ...section, title: v })} max={LIMITS.title} placeholder="Experience" />
      <ol className="space-y-3">
        {section.entries.map((entry, i) => {
          const what = `${label} entry ${i + 1}`;
          return (
            <li key={i} className="rounded-control border border-line bg-bg p-3" data-testid="resume-entry">
              <div className="mb-2 flex items-center justify-between gap-2">
                <p className="min-w-0 truncate text-sm font-medium">{entry.heading.trim() || `Entry ${i + 1}`}</p>
                <ItemButtons
                  what={what}
                  index={i}
                  count={section.entries.length}
                  onMove={(d) => onChange({ ...section, entries: move(section.entries, i, d) })}
                  onRemove={() => onChange({ ...section, entries: section.entries.filter((_, k) => k !== i) })}
                />
              </div>
              <EntryEditor
                entry={entry}
                label={what}
                onChange={(e) => onChange({ ...section, entries: section.entries.map((x, k) => (k === i ? e : x)) })}
              />
            </li>
          );
        })}
      </ol>
      <AddButton onClick={() => onChange({ ...section, entries: [...section.entries, blankEntry()] })}>
        Add entry to {label}
      </AddButton>
    </div>
  );
}

export function ResumeEditor<T extends ResumeDoc & { skill_inventory?: string[] }>({
  value,
  onChange,
  withSkills = false,
}: {
  value: T;
  onChange: (v: T) => void;
  /** the base resume also keeps a list of every skill */
  withSkills?: boolean;
}) {
  const set = (patch: Partial<ResumeDoc & { skill_inventory: string[] }>) => onChange({ ...value, ...patch });
  return (
    <div className="space-y-4" data-testid="resume-editor">
      <section className="rounded-card border border-line bg-surface p-3.5 sm:p-5" aria-labelledby="ed-top">
        <h2 id="ed-top" className="text-base font-semibold">
          Name and contact
        </h2>
        <div className="mt-3 space-y-3">
          <Text label="Name" value={value.name} onChange={(v) => set({ name: v })} max={LIMITS.name} />
          <fieldset>
            <legend className="mb-1 text-[13px] font-medium text-muted">Contact lines</legend>
            <ol className="space-y-1.5">
              {value.contact.map((c, i) => (
                <li key={i} className="flex items-start gap-1" data-testid="resume-contact">
                  <Text
                    hideLabel
                    label={`Contact line ${i + 1}`}
                    value={c}
                    onChange={(v) => set({ contact: value.contact.map((x, k) => (k === i ? v : x)) })}
                    max={LIMITS.contact}
                    placeholder="Email, phone, city or link"
                  />
                  <ItemButtons
                    what={`contact line ${i + 1}`}
                    index={i}
                    count={value.contact.length}
                    onMove={(d) => set({ contact: move(value.contact, i, d) })}
                    onRemove={() => set({ contact: value.contact.filter((_, k) => k !== i) })}
                  />
                </li>
              ))}
            </ol>
            <div className="mt-2">
              <AddButton onClick={() => set({ contact: [...value.contact, ""] })}>Add contact line</AddButton>
            </div>
          </fieldset>
        </div>
      </section>

      <ol className="space-y-4">
        {value.sections.map((section, i) => (
          <li key={i}>
            <section className="rounded-card border border-line bg-surface p-3.5 sm:p-5" aria-label={section.title.trim() || `Section ${i + 1}`} data-testid="resume-section">
              <div className="mb-3 flex items-center justify-between gap-2">
                <h2 className="min-w-0 truncate text-base font-semibold">{section.title.trim() || `Section ${i + 1}`}</h2>
                <ItemButtons
                  what={`section ${section.title.trim() || i + 1}`}
                  index={i}
                  count={value.sections.length}
                  onMove={(d) => set({ sections: move(value.sections, i, d) })}
                  onRemove={() => set({ sections: value.sections.filter((_, k) => k !== i) })}
                />
              </div>
              <SectionEditor
                section={section}
                n={i + 1}
                onChange={(s) => set({ sections: value.sections.map((x, k) => (k === i ? s : x)) })}
              />
            </section>
          </li>
        ))}
      </ol>
      <AddButton onClick={() => set({ sections: [...value.sections, { title: "", entries: [blankEntry()] }] })}>Add section</AddButton>

      {withSkills && (
        <section className="rounded-card border border-line bg-surface p-3.5 sm:p-5" aria-labelledby="ed-skills">
          <h2 id="ed-skills" className="text-base font-semibold">
            Every skill you have
          </h2>
          <p className="mt-0.5 text-sm text-muted">
            Tailored resumes pick from this list, so put everything here, even what doesn&apos;t fit on one page.
          </p>
          <div className="mt-3">
            <ChipInput
              label="Skill list"
              value={value.skill_inventory ?? []}
              onChange={(v) => set({ skill_inventory: v })}
              placeholder="Python"
              max={LIMITS.skills}
              maxLength={LIMITS.skill}
            />
          </div>
        </section>
      )}
    </div>
  );
}

/** What is wrong enough that saving should wait, or null. */
export function resumeProblem(doc: ResumeDoc): string | null {
  if (!doc.name.trim()) return "Add your name.";
  if (!doc.sections.length) return "Add at least one section.";
  return null;
}

/** Drops empty lines and entries, so a stray "+ Add" leaves nothing behind. */
export function tidy<T extends ResumeDoc>(doc: T): T {
  return {
    ...doc,
    name: doc.name.trim(),
    contact: doc.contact.map((c) => c.trim()).filter(Boolean),
    sections: doc.sections
      .map((s) => ({
        title: s.title.trim(),
        entries: s.entries
          .map((e) => ({
            heading: e.heading.trim(),
            right: e.right.trim(),
            sub: e.sub.trim(),
            sub_right: e.sub_right.trim(),
            lines: e.lines.map((l) => l.trim()).filter(Boolean),
          }))
          .filter((e) => e.heading || e.right || e.sub || e.sub_right || e.lines.length),
      }))
      .filter((s) => s.title || s.entries.length),
  };
}
