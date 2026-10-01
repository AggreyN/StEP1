"use client";
// The owner's page, in two parts: Reviews and Users. Anyone else sees the
// not-found page, as if it didn't exist (the API answers them 404 too).
// The part shown is in the URL (?tab=users), so it survives a reload.
import { Suspense, useCallback, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useRequireAuth } from "@/lib/auth";
import { useMe } from "@/lib/me";
import { AppShell } from "@/components/AppShell";
import { NotFound } from "@/components/NotFound";
import { AdminReviews } from "@/components/admin/AdminReviews";
import { AdminUsers } from "@/components/admin/AdminUsers";
import { Spinner } from "@/components/ui";

const TABS = [
  { value: "reviews", label: "Reviews" },
  { value: "users", label: "Users" },
] as const;

function Admin() {
  const authed = useRequireAuth();
  const me = useMe();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [missing, setMissing] = useState(false);
  const onMissing = useCallback(() => setMissing(true), []);
  const tab = params.get("tab") === "users" ? "users" : "reviews";
  const query = params.get("q") ?? "";
  const onQuery = useCallback(
    (q: string) => {
      const p = new URLSearchParams({ tab: "users" });
      if (q) p.set("q", q);
      router.replace(`${pathname}?${p}`, { scroll: false });
    },
    [router, pathname]
  );

  if (!authed) return null;
  if ((me && !me.is_admin) || missing) return <NotFound />;

  return (
    <AppShell>
      <h1 className="text-xl font-semibold tracking-tight">Admin</h1>
      <nav aria-label="Admin sections" className="mb-4 mt-3 flex gap-1 border-b border-line">
        {TABS.map((t) => (
          <Link
            key={t.value}
            href={t.value === "reviews" ? "/admin" : "/admin?tab=users"}
            aria-current={tab === t.value ? "page" : undefined}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${
              tab === t.value ? "border-accent font-semibold text-fg" : "border-transparent text-muted hover:text-fg"
            }`}
          >
            {t.label}
          </Link>
        ))}
      </nav>
      {!me ? (
        <Spinner label="One moment" />
      ) : tab === "users" ? (
        <AdminUsers onMissing={onMissing} query={query} onQuery={onQuery} />
      ) : (
        <AdminReviews onMissing={onMissing} />
      )}
    </AppShell>
  );
}

export default function AdminPage() {
  return (
    <Suspense>
      <Admin />
    </Suspense>
  );
}
