"use client";
// The session lives here and only here: what is stored, where, and how the
// app learns that someone is signed in.
//
// Two ways to sign in, chosen when the site is built (see config.ts):
//   local    the StEP1 API checks an email and password and issues a token
//   cognito  Amazon Cognito's managed login issues the tokens (cognito.ts)
// Either way the rest of the app sees the same thing: a bearer token for the
// API and a user.
//
// WHERE THE TOKENS ARE KEPT, AND WHY
// In memory and in localStorage. That is a deliberate choice, not an
// oversight:
//   - The token is sent in the Authorization header, so there is no cookie
//     and therefore no CSRF surface.
//   - The cost is that script running on the page could read it, so any XSS
//     would be an account takeover. The app is built to leave no room for
//     that: no dangerouslySetInnerHTML (the linter fails the build on it),
//     no user-written HTML anywhere, no third-party scripts, and a
//     Content-Security-Policy that only allows the site's own scripts and
//     only lets them call the API and the sign-in service.
//   - In cognito mode the refresh token is kept the same way, so that a
//     reload doesn't sign the person out every hour. It lives longer than
//     the ID token, which makes the point above matter more, not less.
//   - httpOnly cookies would need a server in front of the API to hold
//     them. The site is static files; there isn't one.

import { useEffect, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { AUTH_MODE } from "./config";
import { refresh, rememberReturnTo, signOutUrl, type Tokens } from "./cognito";
import type { User } from "./types";

const TOKEN_KEY = "step1.token";
const USER_KEY = "step1.user";
const REFRESH_KEY = "step1.refresh"; // cognito mode only
const EXPIRES_KEY = "step1.expires"; // cognito mode only
const NOTICE_KEY = "step1.notice"; // sessionStorage: one message for the sign-in page

let memToken: string | null = null;
let memUser: User | null = null;
let memRefresh: string | null = null;
let memExpires = 0;
let loaded = false;
const listeners = new Set<() => void>();

function load() {
  if (loaded || typeof window === "undefined") return;
  loaded = true;
  try {
    memToken = window.localStorage.getItem(TOKEN_KEY);
    const raw = window.localStorage.getItem(USER_KEY);
    memUser = raw ? (JSON.parse(raw) as User) : null;
    memRefresh = window.localStorage.getItem(REFRESH_KEY);
    memExpires = Number(window.localStorage.getItem(EXPIRES_KEY)) || 0;
  } catch {
    memToken = null;
    memUser = null;
    memRefresh = null;
    memExpires = 0;
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

function store(token: string, user: User, refreshToken: string | null, expiresAt: number) {
  memToken = token;
  memUser = user;
  memRefresh = refreshToken;
  memExpires = expiresAt;
  loaded = true;
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
    window.localStorage.setItem(USER_KEY, JSON.stringify(user));
    if (refreshToken) window.localStorage.setItem(REFRESH_KEY, refreshToken);
    else window.localStorage.removeItem(REFRESH_KEY);
    if (expiresAt) window.localStorage.setItem(EXPIRES_KEY, String(expiresAt));
    else window.localStorage.removeItem(EXPIRES_KEY);
  } catch {
    // storage unavailable (private mode): the in-memory copy still works
  }
  listeners.forEach((l) => l());
}

/** Local mode: the token and user the API returned. */
export function setSession(token: string, user: User) {
  store(token, user, null, 0);
}

/** Cognito mode: the tokens from sign-in or from a refresh. */
export function setCognitoSession(t: Tokens) {
  store(t.token, t.user, t.refreshToken, t.expiresAt);
}

export function clearSession() {
  memToken = null;
  memUser = null;
  memRefresh = null;
  memExpires = 0;
  loaded = true;
  try {
    for (const key of [TOKEN_KEY, USER_KEY, REFRESH_KEY, EXPIRES_KEY]) window.localStorage.removeItem(key);
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

// ---------- staying signed in (cognito mode) ----------

const REFRESH_EARLY_MS = 60_000;
let refreshing: Promise<boolean> | null = null;

/** True when the token is about to stop working and could be replaced. */
export function tokenIsStale(): boolean {
  load();
  return AUTH_MODE === "cognito" && !!memToken && memExpires > 0 && memExpires - Date.now() < REFRESH_EARLY_MS;
}

/** Replaces the tokens using the refresh token. Resolves to false when that
 *  isn't possible; the caller then asks the person to sign in again. Calls
 *  made at the same moment share one request. */
export function refreshSession(): Promise<boolean> {
  load();
  if (AUTH_MODE !== "cognito") return Promise.resolve(false);
  refreshing ??= refresh(memRefresh)
    .then((tokens) => {
      if (!tokens) return false;
      setCognitoSession(tokens);
      return true;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

// ---------- leaving ----------

/** A message for the sign-in page to show once (it survives the trip through
 *  Cognito's sign-out, which a query string on the sign-out URL would not). */
export function leaveNotice(notice: "deleted") {
  try {
    window.sessionStorage.setItem(NOTICE_KEY, notice);
  } catch {
    // ignore
  }
}

export function peekNotice(): string | null {
  try {
    return window.sessionStorage.getItem(NOTICE_KEY);
  } catch {
    return null;
  }
}

export function clearNotice() {
  try {
    window.sessionStorage.removeItem(NOTICE_KEY);
  } catch {
    // ignore
  }
}

/** Where the browser goes to finish signing out. In cognito mode that is
 *  Cognito's sign-out address, which ends its own session and comes back. */
export function signOutDestination(localPath = "/login"): string {
  return (AUTH_MODE === "cognito" && signOutUrl()) || localPath;
}

/** Sign out, deliberately. */
export function signOut() {
  clearSession();
  window.location.assign(signOutDestination());
}

/** The session stopped working (the API answered 401 and it couldn't be
 *  renewed). In cognito mode the page the person was on is remembered, so
 *  signing in again brings them back to it. */
export function sessionEnded() {
  clearSession();
  if (typeof window === "undefined" || window.location.pathname.startsWith("/login")) return;
  if (AUTH_MODE === "cognito") rememberReturnTo(window.location.pathname + window.location.search);
  // A full page load is deliberate: a dead session should drop all in-memory
  // page state.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign("/login?expired=1");
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** "unknown" during prerendering and hydration, then the real answer. */
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
    if (state !== "out") return;
    // Cognito mode: come back here after signing in.
    if (AUTH_MODE === "cognito") rememberReturnTo(window.location.pathname + window.location.search);
    router.replace("/login");
  }, [state, router]);
  return state === "in";
}
