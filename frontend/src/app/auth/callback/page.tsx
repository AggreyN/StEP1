"use client";
// Where Cognito sends the browser after sign-in: /auth/callback?code=...&state=...
// A static page. It finishes the sign-in in the browser (lib/cognito.ts),
// stores the session, and goes on to where the person was heading.
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, getMe } from "@/lib/api";
import { clearSession, setCognitoSession } from "@/lib/auth";
import { PROBLEM_TEXT, SignInError, beginSignIn, finishSignIn, type SignInProblem } from "@/lib/cognito";
import { AUTH_MODE } from "@/lib/config";
import { CONTACT_EMAIL, CONTACT_MAILTO } from "@/lib/site";
import { Wordmark } from "@/components/AppShell";
import { SiteFooter } from "@/components/SiteFooter";
import { Button, Spinner } from "@/components/ui";

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center px-4 py-10">
        <Link href="/" className="self-start">
          <Wordmark />
        </Link>
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}

function Problem({ problem }: { problem: SignInProblem }) {
  const [busy, setBusy] = useState(false);
  const text = PROBLEM_TEXT[problem];
  return (
    <Frame>
      <h1 className="mt-6 text-2xl font-semibold tracking-tight">{text.title}</h1>
      <p role="alert" data-testid="signin-problem" data-problem={problem} className="mt-2 text-[15px] text-muted">
        {text.body}
      </p>
      {problem === "not_invited" && (
        <p className="mt-2 text-[15px] text-muted">
          If you think that is a mistake, write to{" "}
          <a href={CONTACT_MAILTO} className="font-medium text-accent-text underline underline-offset-2">
            {CONTACT_EMAIL}
          </a>
          .
        </p>
      )}
      <div className="mt-6 flex flex-wrap items-center gap-3">
        {problem !== "not_configured" && (
          <Button
            variant="primary"
            busy={busy}
            data-testid="signin-again"
            onClick={() => {
              setBusy(true);
              beginSignIn().catch(() => setBusy(false));
            }}
          >
            {problem === "not_invited" ? "Sign in with another account" : "Sign in again"}
          </Button>
        )}
        <Link href="/about" className="text-sm font-medium text-accent-text underline underline-offset-2">
          About StEP1
        </Link>
      </div>
    </Frame>
  );
}

function Callback() {
  const router = useRouter();
  const params = useSearchParams();
  const query = params.toString();
  const [failed, setFailed] = useState<{ query: string; problem: SignInProblem } | null>(null);

  useEffect(() => {
    if (AUTH_MODE !== "cognito") return;
    let cancelled = false;
    finishSignIn(new URLSearchParams(query))
      .then(async ({ tokens, returnTo }) => {
        setCognitoSession(tokens);
        let onboarded: boolean;
        try {
          onboarded = (await getMe()).onboarded;
        } catch (e) {
          // The sign-in worked but the API won't have this account.
          clearSession();
          throw e instanceof ApiError && (e.status === 401 || e.status === 403)
            ? new SignInError("not_invited", PROBLEM_TEXT.not_invited.body)
            : new SignInError("network", "Signed in, but the StEP1 API could not be reached. Try again in a moment.");
        }
        if (!cancelled) router.replace(onboarded ? (returnTo ?? "/") : "/onboarding");
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setFailed({ query, problem: e instanceof SignInError ? e.problem : "unexpected" });
      });
    return () => {
      cancelled = true;
    };
  }, [query, router]);

  if (AUTH_MODE !== "cognito") {
    return (
      <Frame>
        <h1 className="mt-6 text-2xl font-semibold tracking-tight">Nothing to finish here</h1>
        <p className="mt-2 text-[15px] text-muted" data-testid="callback-unused">
          This address is only used when StEP1 signs people in through Amazon Cognito, and this site does not.
        </p>
        <Link href="/login" className="mt-6 self-start font-medium text-accent-text underline underline-offset-2">
          Go to sign in
        </Link>
      </Frame>
    );
  }

  if (failed?.query === query) return <Problem problem={failed.problem} />;

  return (
    <Frame>
      <h1 className="mt-6 text-2xl font-semibold tracking-tight">Signing you in</h1>
      <div className="mt-3">
        <Spinner label="One moment" />
      </div>
    </Frame>
  );
}

export default function CallbackPage() {
  return (
    <Suspense>
      <Callback />
    </Suspense>
  );
}
