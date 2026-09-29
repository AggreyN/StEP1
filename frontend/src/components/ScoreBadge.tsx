export function ScoreBadge({ score, size = "md" }: { score: number | null; size?: "md" | "lg" }) {
  const dim = size === "lg" ? "h-14 w-14 text-xl" : "h-11 w-11 text-base";
  if (score == null) {
    return (
      <span
        aria-label="Not scored yet"
        title="Not scored yet"
        className={`inline-flex shrink-0 items-center justify-center rounded-control bg-surface-2 font-mono font-semibold text-muted ${dim}`}
      >
        –
      </span>
    );
  }
  return (
    <span
      aria-label={`Match score ${score} out of 100`}
      title="Match score out of 100"
      className={`inline-flex shrink-0 items-center justify-center rounded-control bg-accent font-mono font-semibold text-accent-fg ${dim}`}
    >
      {score}
    </span>
  );
}
