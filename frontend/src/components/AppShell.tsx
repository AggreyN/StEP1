"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { clearSession } from "@/lib/auth";

const NAV = [
  { href: "/", label: "Matches" },
  { href: "/saved", label: "Saved" },
  { href: "/applications", label: "Applications" },
  { href: "/onboarding", label: "Profile" },
];

export function Wordmark() {
  return (
    <span className="text-[17px] font-semibold tracking-tight">
      St<span className="text-accent">EP</span>1
    </span>
  );
}

export function SourcesFooter() {
  return (
    <footer className="mt-auto border-t border-line px-4 py-5 text-center text-xs text-faint">
      Listings from{" "}
      <a className="underline underline-offset-2 hover:text-muted" href="https://github.com/SimplifyJobs/Summer2027-Internships" target="_blank" rel="noreferrer">
        SimplifyJobs
      </a>{" "}
      and{" "}
      <a className="underline underline-offset-2 hover:text-muted" href="https://github.com/vanshb03/Summer2027-Internships" target="_blank" rel="noreferrer">
        vanshb03
      </a>
      . Every listing links out to the original posting. StEP1 doesn&apos;t own or host them.
    </footer>
  );
}

export function AppShell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const path = usePathname();
  const router = useRouter();
  const active = (href: string) =>
    href === "/" ? path === "/" : path === href || path.startsWith(href + "/");
  const width = wide ? "max-w-6xl" : "max-w-3xl";

  return (
    <div className="flex min-h-screen flex-col pb-14 sm:pb-0">
      <header className="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur">
        <div className={`mx-auto flex h-12 items-center gap-2 px-4 sm:h-14 ${width}`}>
          <Link href="/" className="mr-2 sm:mr-6">
            <Wordmark />
          </Link>
          {/* Desktop: links in the header. Phones get the tab bar below. */}
          <nav aria-label="Main" className="hidden min-w-0 flex-1 items-center gap-1 sm:flex">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active(n.href) ? "page" : undefined}
                className={`rounded-chip px-3 py-1.5 text-sm ${
                  active(n.href) ? "bg-surface-2 font-medium text-fg" : "text-muted hover:text-fg"
                }`}
              >
                {n.label}
              </Link>
            ))}
          </nav>
          <button
            onClick={() => {
              clearSession();
              router.replace("/login");
            }}
            className="ml-auto shrink-0 rounded-chip px-2 py-1.5 text-sm text-muted hover:text-fg"
          >
            Sign out
          </button>
        </div>
      </header>

      <main className={`mx-auto w-full flex-1 px-4 py-4 sm:py-5 ${width}`}>{children}</main>
      <SourcesFooter />

      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-20 grid h-14 grid-cols-4 border-t border-line bg-surface sm:hidden"
      >
        {NAV.map((n) => (
          <Link
            key={n.href}
            href={n.href}
            aria-current={active(n.href) ? "page" : undefined}
            className={`flex items-center justify-center text-[13px] ${
              active(n.href) ? "font-semibold text-fg shadow-[inset_0_2px_0_var(--accent)]" : "text-muted"
            }`}
          >
            {n.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}
