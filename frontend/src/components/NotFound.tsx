"use client";
import { useEffect, useSyncExternalStore } from "react";
import Link from "next/link";
import { legacyTarget } from "@/lib/routes";
import { Wordmark } from "./AppShell";
import { SiteFooter } from "./SiteFooter";
import { Spinner } from "./ui";

const never = () => () => {};

export function NotFound() {
  // "unknown" while prerendering and hydrating, then the browser's answer.
  const target = useSyncExternalStore<string | null | "unknown">(
    never,
    () => legacyTarget(window.location.pathname, window.location.search),
    () => "unknown"
  );

  useEffect(() => {
    // A full page load: the address needs a different file.
    if (target && target !== "unknown") window.location.replace(target);
  }, [target]);

  return (
    <div className="flex min-h-screen flex-col">
      <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-4 py-10">
        <Link href="/" className="self-start">
          <Wordmark />
        </Link>
        {target === null ? (
          <>
            <h1 className="mt-6 text-2xl font-semibold tracking-tight">Page not found</h1>
            <p className="mt-1 text-sm text-muted">
              There is nothing at this address. It may have been mistyped, or the page may have moved.
            </p>
            <ul className="mt-5 space-y-2 text-[15px]">
              <li>
                <Link href="/" className="font-medium text-accent-text underline underline-offset-2">
                  Your matches
                </Link>
              </li>
              <li>
                <Link href="/applications" className="font-medium text-accent-text underline underline-offset-2">
                  Your applications
                </Link>
              </li>
              <li>
                <Link href="/about" className="font-medium text-accent-text underline underline-offset-2">
                  About StEP1
                </Link>
              </li>
            </ul>
          </>
        ) : (
          <>
            <h1 className="sr-only">One moment</h1>
            <div className="mt-6">
              <Spinner label="One moment" />
            </div>
          </>
        )}
      </main>
      <SiteFooter />
    </div>
  );
}
