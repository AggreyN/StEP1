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
      <a className="underline underline-offset-2 hover:text-muted" href="https://github.com/SimplifyJobs/Summer2026-Internships" target="_blank" rel="noreferrer">
        SimplifyJobs
      </a>{" "}
      and{" "}
      <a className="underline underline-offset-2 hover:text-muted" href="https://github.com/vanshb03/Summer2027-Internships" target="_blank" rel="noreferrer">
        vanshb03
      </a>{" "}
      — link out to original postings. StEP1 doesn&apos;t own or host these listings.
    </footer>
  );
}

export function AppShell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const path = usePathname();
  const router = useRouter();
  const active = (href: string) =>
    href === "/" ? path === "/" : path === href || path.startsWith(href + "/");

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur">
        <div className={`mx-auto flex h-14 items-center gap-2 px-4 ${wide ? "max-w-6xl" : "max-w-3xl"}`}>
          <Link href="/" className="mr-2 sm:mr-6">
            <Wordmark />
          </Link>
          <nav aria-label="Main" className="flex min-w-0 flex-1 items-center gap-0.5 sm:gap-1">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active(n.href) ? "page" : undefined}
                className={`rounded-md px-2 py-1.5 text-sm sm:px-3 ${
                  active(n.href) ? "bg-surface-2 font-medium text-fg" : "text-muted hover:text-fg"
                } ${n.href === "/onboarding" ? "hidden sm:inline" : ""}`}
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
            className="shrink-0 rounded-md px-2 py-1.5 text-sm text-muted hover:text-fg"
          >
            Sign out
          </button>
        </div>
      </header>
      <main className={`mx-auto w-full flex-1 px-4 py-5 ${wide ? "max-w-6xl" : "max-w-3xl"}`}>{children}</main>
      <SourcesFooter />
    </div>
  );
}
