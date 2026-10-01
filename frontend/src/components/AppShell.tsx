"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { clearSession, signOut } from "@/lib/auth";
import { AUTH_MODE } from "@/lib/config";
import { useMe } from "@/lib/me";
import { SiteFooter } from "./SiteFooter";

const NAV = [
  { href: "/", label: "Matches" },
  { href: "/saved", label: "Saved" },
  { href: "/applications", label: "Applications" },
  { href: "/resumes", label: "Resumes" },
  { href: "/onboarding", label: "Profile" },
];

/** Pages that belong to a tab without living under its address. */
const ALSO = { "/resumes": ["/resume", "/tailor"], "/applications": ["/application"] } as Record<string, string[]>;

export function Wordmark() {
  return (
    <span className="text-[17px] font-semibold tracking-tight">
      St<span className="text-accent">EP</span>1
    </span>
  );
}

export function AppShell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const path = usePathname();
  const router = useRouter();
  const under = (href: string) => path === href || path.startsWith(href + "/");
  const active = (href: string) => (href === "/" ? path === "/" : under(href) || (ALSO[href] ?? []).some(under));
  const width = wide ? "max-w-6xl" : "max-w-3xl";
  // The owner's Admin link, desktop header only. On a phone it sits on the
  // Profile page instead, so the tab bar keeps five items.
  const me = useMe();
  const desktopNav = me?.is_admin ? [...NAV, { href: "/admin", label: "Admin" }] : NAV;

  return (
    <div className="flex min-h-screen flex-col pb-14 sm:pb-0">
      <header className="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur">
        {/* Inside the banner landmark, so it is never content outside a landmark. */}
        <a
          href="#content"
          className="sr-only rounded-control bg-surface px-3 py-2 text-sm font-medium text-fg focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-30"
        >
          Skip to content
        </a>
        <div className={`mx-auto flex h-12 items-center gap-2 px-4 sm:h-14 ${width}`}>
          <Link href="/" className="mr-2 sm:mr-6">
            <Wordmark />
          </Link>
          {/* Desktop: links in the header. Phones get the tab bar below. */}
          <nav aria-label="Main" className="hidden min-w-0 flex-1 items-center gap-1 sm:flex">
            {desktopNav.map((n) => (
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
              if (AUTH_MODE === "cognito") {
                signOut(); // by way of Cognito's sign-out, which ends its session too
                return;
              }
              clearSession();
              router.replace("/login");
            }}
            className="ml-auto shrink-0 rounded-chip px-2 py-1.5 text-sm text-muted hover:text-fg"
          >
            Sign out
          </button>
        </div>
      </header>

      <main id="content" tabIndex={-1} className={`mx-auto w-full flex-1 px-4 py-4 outline-none sm:py-5 ${width}`}>
        {children}
      </main>
      <SiteFooter signedIn />

      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-20 grid h-14 grid-cols-5 border-t border-line bg-surface sm:hidden"
      >
        {NAV.map((n) => (
          <Link
            key={n.href}
            href={n.href}
            aria-current={active(n.href) ? "page" : undefined}
            className={`flex min-w-0 items-center justify-center px-0.5 text-[12px] ${
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
