// The API client. Every backend call in the app goes through this file.
//
// NEXT_PUBLIC_API_BASE selects the backend:
//   "mock"                  → in-browser fixtures (src/lib/mock/), 300 ms delay
//   "http://localhost:8000" → the FastAPI backend
//   unset                   → treated as "mock", with a one-time console warning
//
// Both modes go through the same `send()` and see the same HTTP semantics
// (status codes, Retry-After, {"detail": ...} errors), so switching the env
// var is the only change needed when the backend lands.

import { clearSession, getToken } from "./auth";
import type {
  ApplicationDetail,
  ApplicationSummary,
  AuthResponse,
  FeedFilters,
  FeedSort,
  FeedStatus,
  IngestStatus,
  Me,
  Page,
  Posting,
  Presign,
  Profile,
  ProfileAccepted,
  ProfileInput,
  Resume,
} from "./types";

const RAW_BASE = process.env.NEXT_PUBLIC_API_BASE;
const USE_MOCK = !RAW_BASE || RAW_BASE === "mock";
const BASE = USE_MOCK ? "" : RAW_BASE.replace(/\/+$/, "");

let warned = false;
function warnIfDefaulted() {
  if (!RAW_BASE && !warned && typeof window !== "undefined") {
    warned = true;
    console.warn(
      "[step1] NEXT_PUBLIC_API_BASE is not set — using the in-browser mock API. " +
        "Set it to http://localhost:8000 to use the real backend."
    );
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

type Query = Record<string, string | number | boolean | undefined | null>;

interface SendOpts {
  query?: Query;
  body?: unknown;
  /** false for login/register: a 401 there is "wrong password", not a bounce. */
  authRedirect?: boolean;
}

interface RawResponse {
  status: number;
  headers: Headers;
  body: unknown;
}

function qs(query?: Query): string {
  if (!query) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

function detailOf(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string" && d) return d;
    // FastAPI validation errors: detail is a list of {msg, loc}
    if (Array.isArray(d) && d.length && typeof d[0]?.msg === "string") {
      return d.map((e: { msg: string }) => e.msg).join("; ");
    }
  }
  if (typeof body === "string" && body) return body;
  return `Request failed (${status})`;
}

async function send(method: string, path: string, opts: SendOpts = {}): Promise<RawResponse> {
  const { query, body, authRedirect = true } = opts;
  const token = getToken();
  let res: RawResponse;

  if (USE_MOCK) {
    warnIfDefaulted();
    const { handle } = await import("./mock");
    res = await handle(method, path + qs(query), body, token);
  } else {
    let r: Response;
    try {
      r = await fetch(`${BASE}${path}${qs(query)}`, {
        method,
        headers: {
          ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch {
      throw new ApiError(0, "Can't reach the StEP1 API. Check your connection and try again.");
    }
    const text = await r.text();
    let parsed: unknown = null;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = text;
      }
    }
    res = { status: r.status, headers: r.headers, body: parsed };
  }

  if (res.status === 401 && authRedirect && typeof window !== "undefined") {
    clearSession();
    if (!window.location.pathname.startsWith("/login")) {
      // A hard navigation is deliberate: this module has no router, and a dead
      // session should drop all in-memory page state anyway.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/login?expired=1");
    }
    throw new ApiError(401, "Your session expired — sign in again.");
  }
  if (res.status >= 400) throw new ApiError(res.status, detailOf(res.body, res.status));
  return res;
}

async function json<T>(method: string, path: string, opts?: SendOpts): Promise<T> {
  return (await send(method, path, opts)).body as T;
}

const enc = encodeURIComponent;

// ---------- auth ----------

export function register(email: string, password: string, display_name?: string) {
  return json<AuthResponse>("POST", "/auth/register", {
    body: { email, password, ...(display_name ? { display_name } : {}) },
    authRedirect: false,
  });
}

export function login(email: string, password: string) {
  return json<AuthResponse>("POST", "/auth/login", {
    body: { email, password },
    authRedirect: false,
  });
}

export function getMe() {
  return json<Me>("GET", "/me");
}

// ---------- profile ----------

/** null when the profile has not been created yet (404). */
export async function getProfile(): Promise<Profile | null> {
  try {
    return await json<Profile>("GET", "/profile");
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

/** PUT /profile → 202. Returns the Retry-After poll hint in seconds. */
export async function putProfile(
  input: ProfileInput
): Promise<ProfileAccepted & { retryAfter: number }> {
  const res = await send("PUT", "/profile", { body: input });
  return { ...(res.body as ProfileAccepted), retryAfter: retryAfterOf(res.headers, 1) };
}

function retryAfterOf(h: Headers, fallback: number): number {
  const n = Number(h.get("Retry-After"));
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

export const RESUME_MAX_BYTES = 5 * 1024 * 1024;

/** Client-side check before any network call. Returns an error string or null. */
export function validateResume(file: File): string | null {
  const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
  if (!isPdf) return "Resume must be a PDF.";
  if (file.size > RESUME_MAX_BYTES) return "Resume must be 5 MB or smaller.";
  return null;
}

/** presign → PUT the bytes → commit. Returns the parsed resume. */
export async function uploadResume(file: File): Promise<Resume> {
  const err = validateResume(file);
  if (err) throw new ApiError(422, err);
  const presign = await json<Presign>("POST", "/profile/resume/presign", {
    body: { filename: file.name, content_type: "application/pdf" },
  });
  await putUpload(presign, file);
  return json<Resume>("POST", "/profile/resume/commit", {
    body: { key: presign.key, filename: file.name },
  });
}

/** The one place that PUTs file bytes to the upload URL, and the one place
 *  that decides whether the bearer token goes with them.
 *
 *  Local backend mode: upload_url is our own API, which requires the bearer.
 *  S3: a presigned URL carries its own signature in the query string and must
 *  not be sent a second credential, so the bearer is dropped. */
async function putUpload(p: Presign, file: File): Promise<void> {
  const token = getToken();
  const presigned = /[?&](X-Amz-Signature|Signature)=/i.test(p.upload_url);
  const headers: Record<string, string> = {
    ...p.headers,
    ...(token && !presigned ? { Authorization: `Bearer ${token}` } : {}),
  };
  if (USE_MOCK) {
    const { handleUpload } = await import("./mock");
    await handleUpload(p.upload_url, file);
    return;
  }
  let r: Response;
  try {
    r = await fetch(p.upload_url, { method: p.method || "PUT", headers, body: file });
  } catch {
    throw new ApiError(0, "Upload failed — check your connection and try again.");
  }
  if (!r.ok) {
    let body: unknown = null;
    try {
      body = await r.json();
    } catch {
      // non-JSON (S3 returns XML)
    }
    throw new ApiError(r.status, detailOf(body, r.status));
  }
}

// ---------- feed ----------

export const PAGE_SIZE = 20;

function feedQuery(f: Partial<FeedFilters>, page: number, page_size: number, sort: FeedSort): Query {
  return {
    page,
    page_size,
    // Always sent, so the order on screen never depends on the server default.
    sort,
    roles: f.roles?.length ? f.roles.join(",") : undefined,
    location: f.location || undefined,
    term: f.term || undefined,
    min_score: f.min_score ?? undefined,
    remote: f.remote ? "true" : undefined,
  };
}

export function getFeed(
  f: Partial<FeedFilters>,
  page = 1,
  page_size = PAGE_SIZE,
  sort: FeedSort = "recent"
) {
  return json<Page<Posting>>("GET", "/feed", { query: feedQuery(f, page, page_size, sort) });
}

export async function getFeedStatus(): Promise<FeedStatus & { retryAfter: number | null }> {
  const res = await send("GET", "/feed/status");
  const h = res.headers.get("Retry-After");
  return { ...(res.body as FeedStatus), retryAfter: h ? retryAfterOf(res.headers, 1) : null };
}

/** How fresh the listings are. This only feeds one informational line, so a
 *  401 here never signs the user out — the feed call decides that. Callers
 *  treat any failure (an older backend without the route, the network) as
 *  "nothing to show". */
export function getIngestStatus() {
  return json<IngestStatus>("GET", "/ingest/status", { authRedirect: false });
}

export function getPosting(id: string) {
  return json<Posting>("GET", `/postings/${enc(id)}`);
}

// ---------- saved ----------

export function getSaved(page = 1, page_size = PAGE_SIZE) {
  return json<Page<Posting>>("GET", "/saved", { query: { page, page_size } });
}

export async function savePosting(id: string): Promise<void> {
  await send("POST", `/saved/${enc(id)}`);
}

export async function unsavePosting(id: string): Promise<void> {
  await send("DELETE", `/saved/${enc(id)}`);
}

// ---------- applications ----------

export async function getApplications(): Promise<ApplicationSummary[]> {
  return (await json<{ items: ApplicationSummary[] }>("GET", "/applications")).items;
}

export function createApplication(posting_id: string, applied_at?: string) {
  return json<ApplicationDetail>("POST", "/applications", {
    body: { posting_id, ...(applied_at ? { applied_at } : {}) },
  });
}

export function getApplication(id: number | string) {
  return json<ApplicationDetail>("GET", `/applications/${enc(String(id))}`);
}

export function addEvent(
  id: number | string,
  ev: { kind: string; occurred_at?: string; note?: string }
) {
  return json<ApplicationDetail>("POST", `/applications/${enc(String(id))}/events`, {
    body: ev,
  });
}
