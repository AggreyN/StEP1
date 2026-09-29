"use client";
import { Suspense, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { getMe, login, register } from "@/lib/api";
import { setSession } from "@/lib/auth";
import { SourcesFooter, Wordmark } from "@/components/AppShell";
import { Button, ErrorNote } from "@/components/ui";

const input =
  "h-11 w-full rounded-control border border-line-strong bg-surface px-3 text-[15px] text-fg placeholder:text-faint focus:border-accent focus:outline-none";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setBusy(true);
    try {
      const res =
        mode === "login"
          ? await login(email.trim(), password)
          : await register(email.trim(), password, name.trim() || undefined);
      setSession(res.access_token, res.user);
      const me = await getMe();
      router.replace(me.onboarded ? "/" : "/onboarding");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col">
      <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center px-4 py-10">
        <div className="mb-8">
          <Wordmark />
          <h1 className="mt-4 text-2xl font-semibold tracking-tight">
            {mode === "login" ? "Sign in" : "Create your account"}
          </h1>
          <p className="mt-1 text-sm text-muted">
            Internships ranked against your fields and skills, and every application in one timeline.
          </p>
        </div>

        {params.get("expired") && mode === "login" && !error && (
          <p className="mb-4 rounded-control bg-surface-2 px-3 py-2 text-sm text-muted">
            Your session expired. Sign in again to pick up where you left off.
          </p>
        )}

        <div role="tablist" aria-label="Sign in or register" className="mb-5 grid grid-cols-2 rounded-control border border-line-strong bg-surface-2 p-0.5 text-sm">
          {(["login", "register"] as const).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={mode === m}
              onClick={() => {
                setMode(m);
                setError(null);
              }}
              className={`h-9 rounded-chip border font-medium ${
                mode === m ? "border-line-strong bg-surface text-fg" : "border-transparent text-muted"
              }`}
            >
              {m === "login" ? "Sign in" : "Register"}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="space-y-4" noValidate>
          {mode === "register" && (
            <label className="block">
              <span className="mb-1 block text-sm font-medium">Name <span className="font-normal text-faint">(optional)</span></span>
              <input className={input} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
            </label>
          )}
          <label className="block">
            <span className="mb-1 block text-sm font-medium">Email</span>
            <input
              className={input}
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              placeholder="you@umd.edu"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium">Password</span>
            <input
              className={input}
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
            />
            {mode === "register" && <span className="mt-1 block text-xs text-faint">At least 8 characters.</span>}
          </label>
          {error && <ErrorNote>{error}</ErrorNote>}
          <Button type="submit" variant="primary" className="w-full" disabled={busy || !email || !password}>
            {busy ? "One moment…" : mode === "login" ? "Sign in" : "Create account"}
          </Button>
        </form>
      </main>
      <SourcesFooter />
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
