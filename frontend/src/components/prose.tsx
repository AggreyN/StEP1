// Shared pieces of the two public, long-form pages (About and Privacy):
// serif prose in a narrow column, sans for labels, hairline rules.
import Link from "next/link";
import type { ReactNode } from "react";
import { SiteFooter } from "./SiteFooter";

export function Rule() {
  return <hr className="my-11 border-0 border-t border-[var(--line)]" />;
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h2 className="font-ui mb-[18px] text-[0.76rem] font-semibold uppercase tracking-[0.12em] text-[var(--accent)]">
      {children}
    </h2>
  );
}

/** Paragraph spacing and measure for a run of prose. */
export function Paragraphs({ children }: { children: ReactNode }) {
  return <div className="[&>p]:mb-[18px] [&>p]:max-w-[62ch] [&>p:last-child]:mb-0">{children}</div>;
}

export function ProsePage({ here, children }: { here: string; children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <main className="mx-auto w-full max-w-[660px] px-5 pb-20 pt-14 font-prose text-base leading-[1.65] text-[var(--ink)]">
        <nav aria-label="Breadcrumb" className="font-ui mb-14 flex flex-wrap items-baseline gap-[14px] text-[0.78rem]">
          <Link href="/" className="font-semibold tracking-[0.02em] text-[var(--ink)] no-underline">
            StEP1
          </Link>
          <span aria-current="page" className="text-[var(--ink-3)]">
            {here}
          </span>
        </nav>
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}
