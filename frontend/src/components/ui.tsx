// Small primitives shared by every screen.
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-accent-fg hover:bg-accent-hover border border-transparent",
  secondary: "bg-surface text-fg border border-line-strong hover:bg-surface-2",
  ghost: "bg-transparent text-muted hover:text-fg hover:bg-surface-2 border border-transparent",
  danger: "bg-surface text-danger border border-line-strong hover:bg-danger-soft",
};

export function Button({
  variant = "secondary",
  size = "md",
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  const sz = size === "sm" ? "h-9 px-3 text-sm" : "h-11 px-4 text-[15px]";
  return (
    <button
      className={`inline-flex items-center justify-center gap-1.5 rounded-control font-medium transition-colors disabled:opacity-45 disabled:cursor-not-allowed ${sz} ${VARIANTS[variant]} ${className}`}
      {...rest}
    />
  );
}

export function Chip({
  children,
  tone = "neutral",
  className = "",
  title,
}: {
  children: ReactNode;
  tone?: "neutral" | "outline" | "strong";
  className?: string;
  title?: string;
}) {
  const t =
    tone === "strong"
      ? "bg-surface-2 text-fg border-line"
      : tone === "outline"
        ? "bg-transparent text-muted border-line"
        : "bg-surface-2 text-muted border-transparent";
  return (
    <span
      title={title}
      className={`inline-flex max-w-full items-center gap-1 rounded-chip border px-2 py-0.5 text-[13px] leading-5 ${t} ${className}`}
    >
      {children}
    </span>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-muted">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-line-strong border-t-accent" />
      {label}
    </span>
  );
}

export function ErrorNote({ children, onRetry }: { children: ReactNode; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger"
    >
      <span>{children}</span>
      {onRetry && (
        <button onClick={onRetry} className="font-medium underline underline-offset-2">
          Try again
        </button>
      )}
    </div>
  );
}

export function ProgressBar({ pct, label }: { pct: number; label: string }) {
  const v = Math.max(0, Math.min(100, Math.round(pct)));
  // Drawn as SVG so the width is an attribute, not an inline style: the
  // site's Content-Security-Policy does not allow style attributes.
  return (
    <svg
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={v}
      viewBox="0 0 100 2"
      preserveAspectRatio="none"
      className="block h-2 w-full overflow-hidden rounded-chip"
    >
      <rect width="100" height="2" className="fill-surface-2" />
      <rect width={v} height="2" className="fill-accent" />
    </svg>
  );
}

/** Loading placeholder rows shaped like posting cards. */
export function CardSkeletons({ n = 4 }: { n?: number }) {
  return (
    <div aria-hidden className="space-y-3">
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="h-32 animate-pulse rounded-card border border-line bg-surface" />
      ))}
    </div>
  );
}
