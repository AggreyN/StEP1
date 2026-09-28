export function ScoreBadge({ score, size = "md" }: { score: number; size?: "md" | "lg" }) {
  const dim = size === "lg" ? "h-14 w-14 text-xl" : "h-11 w-11 text-base";
  return (
    <span
      aria-label={`Match score ${score} out of 100`}
      title="Match score out of 100"
      className={`tnum inline-flex shrink-0 items-center justify-center rounded-lg bg-accent font-semibold text-accent-fg ${dim}`}
    >
      {score}
    </span>
  );
}
