import { kindLabel, statusTone, type Tone } from "@/lib/labels";

const TONES: Record<Tone, string> = {
  accent: "bg-accent-soft text-accent-text",
  neutral: "bg-surface-2 text-fg",
  positive: "bg-positive-soft text-positive",
  negative: "bg-danger-soft text-danger",
  // Ghosted / withdrawn: quiet on purpose — greyed, never red.
  quiet: "bg-transparent text-faint border border-dashed border-line-strong",
};

export function StatusPill({ status, className = "" }: { status: string; className?: string }) {
  return (
    <span
      data-testid="status-pill"
      data-status={status}
      className={`inline-flex items-center whitespace-nowrap rounded-md px-2 py-0.5 text-[13px] font-medium leading-5 ${TONES[statusTone(status)]} ${className}`}
    >
      {kindLabel(status)}
    </span>
  );
}
