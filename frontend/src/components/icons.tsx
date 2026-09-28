// Inline SVG icons (no icon library). 20px, currentColor.
type P = { className?: string };
const base = "h-5 w-5 shrink-0";

export const StarIcon = ({ filled, className = "" }: P & { filled?: boolean }) => (
  <svg viewBox="0 0 20 20" className={`${base} ${className}`} aria-hidden fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth={1.5}>
    <path strokeLinejoin="round" d="M10 2.5l2.3 4.8 5.2.7-3.8 3.6.9 5.2L10 14.3l-4.6 2.5.9-5.2L2.5 8l5.2-.7L10 2.5z" />
  </svg>
);
export const CheckIcon = ({ className = "" }: P) => (
  <svg viewBox="0 0 20 20" className={`h-4 w-4 shrink-0 ${className}`} aria-hidden fill="none" stroke="currentColor" strokeWidth={2}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 10.5l3.5 3.5 7.5-8" />
  </svg>
);
export const ExternalIcon = ({ className = "" }: P) => (
  <svg viewBox="0 0 20 20" className={`h-3.5 w-3.5 shrink-0 ${className}`} aria-hidden fill="none" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M11 4h5v5M16 4l-7 7M14 11.5V16H4V6h4.5" />
  </svg>
);
export const UpIcon = ({ className = "" }: P) => (
  <svg viewBox="0 0 20 20" className={`${base} ${className}`} aria-hidden fill="none" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M5 12l5-5 5 5" />
  </svg>
);
export const DownIcon = ({ className = "" }: P) => (
  <svg viewBox="0 0 20 20" className={`${base} ${className}`} aria-hidden fill="none" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M5 8l5 5 5-5" />
  </svg>
);
export const XIcon = ({ className = "" }: P) => (
  <svg viewBox="0 0 20 20" className={`h-4 w-4 shrink-0 ${className}`} aria-hidden fill="none" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" d="M5 5l10 10M15 5L5 15" />
  </svg>
);
export const FilterIcon = ({ className = "" }: P) => (
  <svg viewBox="0 0 20 20" className={`h-4 w-4 shrink-0 ${className}`} aria-hidden fill="none" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" d="M3 5h14M6 10h8M8.5 15h3" />
  </svg>
);
