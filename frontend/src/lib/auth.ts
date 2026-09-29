"use client";
// Token handling lives here and only here.
//
// WHERE THE TOKEN IS KEPT, AND WHY
// The sign-in token is kept in memory and in localStorage. That is a
// deliberate choice, not an oversight:
//   - It is a bearer token sent in the Authorization header, so there is no
//     cookie and therefore no CSRF surface.
//   - The cost is that script running on the page could read it, so any XSS
//     would be an account takeover. The app is built to leave no room for
//     that: no dangerouslySetInnerHTML (the linter fails the build on it),
//     no user-written HTML anywhere, no third-party scripts, and a
//     Content-Security-Policy that only allows the site's own scripts.
//   - Moving to httpOnly cookies would trade this for CSRF protection work
//     and a harder Cognito swap. For an invite-only app that is the wrong
//     trade today. Revisit it if the app ever renders user-supplied markup.
//
// TODO(cognito): this whole file is replaced by Cognito's hosted UI. The rest
// of the app only calls getToken / setSession / clearSession / useRequireAuth,
// so the swap is one file.

import { useEffect, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import type { User } from "./types";

const TOKEN_KEY = "step1.token";
const USER_KEY = "step1.user";

let memToken: string | null = null;
let memUser: User | null = null;
let loaded = false;
const listeners = new Set<() => void>();

function load() {
  if (loaded || typeof window === "undefined") return;
  loaded = true;
  try {
    memToken = window.localStorage.getItem(TOKEN_KEY);
    const raw = window.localStorage.getItem(USER_KEY);
    memUser = raw ? (JSON.parse(raw) as User) : null;
  } catch {
    memToken = null;
    memUser = null;
  }
}

export function getToken(): string | null {
  load();
  return memToken;
}

export function getUser(): User | null {
  load();
  return memUser;
}

export function setSession(token: string, user: User) {
  memToken = token;
  memUser = user;
  loaded = true;
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
    window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    // storage unavailable (private mode) — the in-memory copy still works
  }
  listeners.forEach((l) => l());
}

export function clearSession() {
  memToken = null;
  memUser = null;
  loaded = true;
  try {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(USER_KEY);
  } catch {
    // ignore
  }
  listeners.forEach((l) => l());
}

/** After the account is deleted: forget the session and anything else this
 *  app put in the browser for the user. */
export function clearLocalState() {
  clearSession();
  try {
    for (const store of [window.localStorage, window.sessionStorage]) {
      for (const key of Object.keys(store)) {
        // keep the in-browser mock API's own "server" data and test switches
        if (key.startsWith("step1.") && !key.startsWith("step1.mock.")) store.removeItem(key);
      }
    }
  } catch {
    // ignore
  }
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** "unknown" during SSR/hydration, then the real answer on the client. */
export function useAuthState(): "unknown" | "in" | "out" {
  return useSyncExternalStore(
    subscribe,
    () => (getToken() ? "in" : "out"),
    () => "unknown"
  );
}

/** Every signed-in route calls this. Redirects to /login when there is no
 *  token; returns true once it is safe to fetch. */
export function useRequireAuth(): boolean {
  const state = useAuthState();
  const router = useRouter();
  useEffect(() => {
    if (state === "out") router.replace("/login");
  }, [state, router]);
  return state === "in";
}
