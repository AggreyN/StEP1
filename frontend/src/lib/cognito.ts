"use client";
// Sign-in with Amazon Cognito's managed login: the authorization code flow
// with PKCE, from a public client (no client secret).
//
//   1. beginSignIn()   makes a code verifier, a state and a nonce, keeps them
//                      in this tab's sessionStorage, and sends the browser to
//                      <domain>/oauth2/authorize.
//   2. Cognito signs the person in and sends the browser back to
//      /auth/callback?code=...&state=...
//   3. finishSignIn()  checks the state, exchanges the code (with the
//                      verifier) at <domain>/oauth2/token, checks the ID
//                      token's nonce and audience, and stores the session.
//
// The endpoints and their parameters are Cognito's, from the Amazon Cognito
// developer guide ("The redirect and authorization endpoint", "The token
// issuer endpoint", "The managed login sign-out endpoint", "Using PKCE in
// authorization code grants").
import { API_TOKEN_USE, COGNITO } from "./config";
import type { User } from "./types";

const PENDING_KEY = "step1.signin"; // sessionStorage: one sign-in in progress, per tab
const RETURN_KEY = "step1.returnTo"; // sessionStorage: where to go afterwards

export type SignInProblem =
  | "cancelled"
  | "state"
  | "expired"
  | "not_invited"
  | "unexpected"
  | "network"
  | "nothing"
  | "not_configured";

export class SignInError extends Error {
  problem: SignInProblem;
  constructor(problem: SignInProblem, message: string) {
    super(message);
    this.problem = problem;
  }
}

/** What the person is told, in plain words. */
export const PROBLEM_TEXT: Record<SignInProblem, { title: string; body: string }> = {
  cancelled: {
    title: "Sign-in was cancelled",
    body: "You left sign-in before it finished. Nothing was changed.",
  },
  state: {
    title: "Sign-in was stopped",
    body: "This sign-in was not started from this browser tab, so it was stopped to keep your account safe. Start again from here.",
  },
  expired: {
    title: "That sign-in ran out of time",
    body: "It took too long, or the link was already used. Start again and it will work.",
  },
  not_invited: {
    title: "That account has not been invited",
    body: "StEP1 is invite only for now, and this account is not on the list.",
  },
  unexpected: {
    title: "Sign-in did not finish",
    body: "The sign-in service sent back something unexpected, so it was stopped. Start again.",
  },
  network: {
    title: "Could not reach the sign-in service",
    body: "Check your connection and try again.",
  },
  nothing: {
    title: "Nothing to finish here",
    body: "This address is where sign-in ends up. There is no sign-in in progress.",
  },
  not_configured: {
    title: "Sign-in is not set up",
    body: "This site was built without its sign-in settings. Tell whoever runs it.",
  },
};

// ---------- small helpers ----------

function base64url(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function random(bytes: number): string {
  return base64url(crypto.getRandomValues(new Uint8Array(bytes)));
}

async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64url(new Uint8Array(digest));
}

/** The claims of a JWT. The signature is not checked here: the token comes
 *  straight from Cognito's token endpoint over TLS, and the API verifies the
 *  signature on every request. */
export function claimsOf(token: string): Record<string, unknown> | null {
  try {
    const part = token.split(".")[1];
    const binary = atob(part.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(part.length / 4) * 4, "="));
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(bytes)) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function configured(): boolean {
  return !!(COGNITO.domain && COGNITO.clientId && COGNITO.redirectUri && COGNITO.logoutUri);
}

/** Only addresses inside this site, so a crafted link can't send someone elsewhere. */
function safePath(p: string | null | undefined): string | null {
  if (!p || !p.startsWith("/") || p.startsWith("//") || p.startsWith("/login") || p.startsWith("/auth/")) return null;
  return p;
}

// ---------- where to go after signing in ----------

export function rememberReturnTo(path: string) {
  const safe = safePath(path);
  try {
    if (safe) window.sessionStorage.setItem(RETURN_KEY, safe);
  } catch {
    // ignore
  }
}

function takeReturnTo(): string | null {
  try {
    const v = window.sessionStorage.getItem(RETURN_KEY);
    window.sessionStorage.removeItem(RETURN_KEY);
    return safePath(v);
  } catch {
    return null;
  }
}

// ---------- step 1: leave for Cognito ----------

export async function beginSignIn(): Promise<void> {
  if (!configured()) throw new SignInError("not_configured", PROBLEM_TEXT.not_configured.body);
  // 64 random bytes make an 86-character verifier (the limit is 43 to 128).
  const verifier = random(64);
  const state = random(24);
  const nonce = random(24);
  const pending = { verifier, state, nonce, returnTo: takeReturnTo(), startedAt: Date.now() };
  window.sessionStorage.setItem(PENDING_KEY, JSON.stringify(pending));

  const q = new URLSearchParams({
    response_type: "code",
    client_id: COGNITO.clientId,
    redirect_uri: COGNITO.redirectUri,
    scope: COGNITO.scope,
    state,
    nonce,
    code_challenge_method: "S256",
    code_challenge: await challengeFor(verifier),
  });
  // Another site: Cognito's managed login.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign(`${COGNITO.domain}/oauth2/authorize?${q}`);
}

// ---------- step 3: back from Cognito ----------

export interface Tokens {
  /** The token sent to the API (the ID token). */
  token: string;
  refreshToken: string | null;
  /** When `token` stops being valid, in milliseconds since 1970. */
  expiresAt: number;
  user: User;
}

interface TokenResponse {
  id_token?: string;
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
  error?: string;
  error_description?: string;
}

async function tokenRequest(form: Record<string, string>): Promise<{ status: number; body: TokenResponse }> {
  let r: Response;
  try {
    r = await fetch(`${COGNITO.domain}/oauth2/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(form),
    });
  } catch {
    throw new SignInError("network", PROBLEM_TEXT.network.body);
  }
  let body: TokenResponse = {};
  try {
    body = (await r.json()) as TokenResponse;
  } catch {
    // an empty or non-JSON body is handled by the status alone
  }
  return { status: r.status, body };
}

function tokensFrom(body: TokenResponse, expect: { nonce?: string }, keepRefresh: string | null): Tokens {
  const token = body.id_token;
  const claims = token ? claimsOf(token) : null;
  if (!token || !claims) throw new SignInError("unexpected", PROBLEM_TEXT.unexpected.body);
  const exp = typeof claims.exp === "number" ? claims.exp * 1000 : 0;
  const audience = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  if (
    claims.token_use !== API_TOKEN_USE ||
    !audience.includes(COGNITO.clientId) ||
    exp <= Date.now() ||
    typeof claims.sub !== "string" ||
    (expect.nonce !== undefined && claims.nonce !== expect.nonce)
  ) {
    throw new SignInError("unexpected", PROBLEM_TEXT.unexpected.body);
  }
  return {
    token,
    refreshToken: body.refresh_token ?? keepRefresh,
    expiresAt: exp,
    user: {
      id: claims.sub,
      email: typeof claims.email === "string" ? claims.email : "",
      display_name: typeof claims.name === "string" && claims.name ? claims.name : null,
    },
  };
}

const notInvited = (text: string) =>
  /not\s+(been\s+)?invited|sign\s*up\s+is\s+not\s+permitted|not\s+permitted|not\s+authorized|presignup/i.test(text);

// One exchange per code, however many times the page renders.
const exchanges = new Map<string, Promise<{ tokens: Tokens; returnTo: string | null }>>();

export function finishSignIn(params: URLSearchParams): Promise<{ tokens: Tokens; returnTo: string | null }> {
  const key = params.toString();
  let running = exchanges.get(key);
  if (!running) {
    running = exchange(params);
    exchanges.set(key, running);
  }
  return running;
}

async function exchange(params: URLSearchParams): Promise<{ tokens: Tokens; returnTo: string | null }> {
  if (!configured()) throw new SignInError("not_configured", PROBLEM_TEXT.not_configured.body);

  let pending: { verifier: string; state: string; nonce: string; returnTo: string | null } | null = null;
  try {
    pending = JSON.parse(window.sessionStorage.getItem(PENDING_KEY) ?? "null");
    window.sessionStorage.removeItem(PENDING_KEY); // single use, whatever happens next
  } catch {
    pending = null;
  }

  const error = params.get("error");
  const code = params.get("code");
  const state = params.get("state");
  if (!error && !code) throw new SignInError("nothing", PROBLEM_TEXT.nothing.body);

  // The state is checked first, for errors too: a reply that doesn't belong
  // to a sign-in this tab started is not believed about anything.
  if (!pending || !state || state !== pending.state) throw new SignInError("state", PROBLEM_TEXT.state.body);

  if (error) {
    const description = params.get("error_description") ?? "";
    if (notInvited(description)) throw new SignInError("not_invited", PROBLEM_TEXT.not_invited.body);
    if (error === "access_denied") throw new SignInError("cancelled", PROBLEM_TEXT.cancelled.body);
    throw new SignInError("unexpected", PROBLEM_TEXT.unexpected.body);
  }

  const { status, body } = await tokenRequest({
    grant_type: "authorization_code",
    client_id: COGNITO.clientId,
    code: code!,
    redirect_uri: COGNITO.redirectUri,
    code_verifier: pending.verifier,
  });
  if (status !== 200) {
    // invalid_grant: the code was used already, has expired, or the verifier
    // doesn't match the challenge it was issued for.
    if (body.error === "invalid_grant") throw new SignInError("expired", PROBLEM_TEXT.expired.body);
    if (notInvited(body.error_description ?? "")) throw new SignInError("not_invited", PROBLEM_TEXT.not_invited.body);
    throw new SignInError("unexpected", PROBLEM_TEXT.unexpected.body);
  }
  return { tokens: tokensFrom(body, { nonce: pending.nonce }, null), returnTo: safePath(pending.returnTo) };
}

// ---------- staying signed in ----------

/** New tokens from the refresh token, or null if it can't be done (there is
 *  no refresh token, or Cognito no longer accepts it). */
export async function refresh(refreshToken: string | null): Promise<Tokens | null> {
  if (!refreshToken || !configured()) return null;
  try {
    const { status, body } = await tokenRequest({
      grant_type: "refresh_token",
      client_id: COGNITO.clientId,
      refresh_token: refreshToken,
    });
    if (status !== 200) return null;
    // A refreshed ID token has no nonce to compare. Cognito returns a new
    // refresh token only when rotation is on; otherwise the old one stays.
    return tokensFrom(body, {}, refreshToken);
  } catch {
    return null;
  }
}

// ---------- signing out ----------

/** Cognito's sign-out address: it ends the managed login session, then sends
 *  the browser to the sign-out URL. */
export function signOutUrl(): string | null {
  if (!configured()) return null;
  const q = new URLSearchParams({ client_id: COGNITO.clientId, logout_uri: COGNITO.logoutUri });
  return `${COGNITO.domain}/logout?${q}`;
}
