// In-browser mock of the StEP1 API. Only src/lib/api.ts imports this.
//
// It speaks HTTP semantics (status, headers, {"detail"} errors) so api.ts runs
// the same code path in both modes. State is seeded from the JSON fixtures,
// kept in memory, and mirrored to localStorage so a page reload (e.g. a
// filtered dashboard URL) sees the same saves/applications.
//
// Test knobs (localStorage):
//   step1.mock.instant = "1"            GET /feed/status reports `ready` on
//                                       the very first poll
//   step1.mock.fail = "POST /saved"     the next request whose "METHOD /path"
//                                       starts with this fails once with a 500

import feedData from "./feed.json";
import profileData from "./profile.json";
import applicationsData from "./applications.json";
import statusData from "./status.json";
import transitionsData from "./transitions.json";
import type {
  ApplicationDetail,
  ApplicationEvent,
  FeedStatus,
  Posting,
  Profile,
  ProfileInput,
  Resume,
} from "../types";
import { roleLabel } from "../roles";

const DELAY_MS = 300;
const STORE_KEY = "step1.mock.v2";
const DEMO_EMAIL = "demo@umd.edu";


const GRAPH = transitionsData.graph as Record<string, string[]>;
const NON_STATUS = new Set(transitionsData.non_status_kinds);
const POSTINGS = feedData.items as Posting[];

interface MockUser {
  id: number;
  email: string;
  display_name: string | null;
}
interface MockApp {
  id: number;
  posting_id: string;
  applied_at: string;
  events: ApplicationEvent[];
}
interface State {
  users: Record<string, MockUser>;
  profiles: Record<string, Profile>;
  resumes: Record<string, Resume>;
  saved: string[];
  apps: MockApp[];
  nextId: number;
  buildStartedAt: number | null; // null = not building
}

function seed(): State {
  return {
    users: { [DEMO_EMAIL]: { id: 1, email: DEMO_EMAIL, display_name: "Demo Terp" } },
    profiles: { [DEMO_EMAIL]: profileData as Profile },
    resumes: {},
    saved: POSTINGS.filter((p) => p.saved).map((p) => p.id),
    apps: applicationsData.items as MockApp[],
    nextId: 100,
    buildStartedAt: null,
  };
}

let state: State | null = null;

function db(): State {
  if (state) return state;
  try {
    const raw = typeof window !== "undefined" ? window.localStorage.getItem(STORE_KEY) : null;
    state = raw ? (JSON.parse(raw) as State) : seed();
  } catch {
    state = seed();
  }
  return state;
}

function persist() {
  try {
    window.localStorage.setItem(STORE_KEY, JSON.stringify(state));
  } catch {
    // storage unavailable — in-memory only
  }
}

interface MockResponse {
  status: number;
  headers: Headers;
  body: unknown;
}

function ok(body: unknown, status = 200, headers: Record<string, string> = {}): MockResponse {
  return { status, headers: new Headers(headers), body };
}
function err(status: number, detail: string): MockResponse {
  return ok({ detail }, status);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const nowIso = () => new Date().toISOString();

function userFromToken(token: string | null): MockUser | null {
  if (!token?.startsWith("mock.")) return null;
  try {
    const email = decodeURIComponent(atob(token.slice(5)));
    return db().users[email] ?? null;
  } catch {
    return null;
  }
}

function authResponse(u: MockUser) {
  return {
    access_token: "mock." + btoa(encodeURIComponent(u.email)),
    token_type: "bearer",
    user: u,
  };
}

function statusOf(app: MockApp): string {
  let s = "applied";
  const sorted = [...app.events].sort((a, b) => a.occurred_at.localeCompare(b.occurred_at));
  for (const e of sorted) if (!NON_STATUS.has(e.kind)) s = e.kind;
  return s;
}

function decorate(p: Posting): Posting {
  const s = db();
  const app = s.apps.find((a) => a.posting_id === p.id);
  return {
    ...p,
    saved: s.saved.includes(p.id),
    application: app ? { id: app.id, status: statusOf(app) } : null,
  };
}

function appDetail(app: MockApp): ApplicationDetail {
  const posting = POSTINGS.find((p) => p.id === app.posting_id)!;
  const status = statusOf(app);
  return {
    id: app.id,
    posting: decorate(posting),
    status,
    applied_at: app.applied_at,
    events: [...app.events].sort((a, b) => a.occurred_at.localeCompare(b.occurred_at)),
    next_transitions: GRAPH[status] ?? [],
  };
}

function sortPostings(list: Posting[]): Posting[] {
  return [...list].sort(
    (a, b) => b.score - a.score || b.date_posted.localeCompare(a.date_posted)
  );
}

function paginate(list: Posting[], q: URLSearchParams) {
  const page = Math.max(1, Number(q.get("page")) || 1);
  const size = Math.min(100, Math.max(1, Number(q.get("page_size")) || 20));
  const items = list.slice((page - 1) * size, page * size);
  return { items, page, total: list.length, has_more: page * size < list.length };
}

/** Same filter semantics the real /feed applies. */
function filterFeed(q: URLSearchParams): Posting[] {
  const roles = (q.get("roles") || "").split(",").filter(Boolean);
  const location = (q.get("location") || "").trim().toLowerCase();
  const term = q.get("term") || "";
  const minScore = Number(q.get("min_score")) || 0;
  const remote = q.get("remote") === "true";
  return POSTINGS.filter(
    (p) =>
      (!roles.length || p.roles.some((r) => roles.includes(r))) &&
      (!location || p.locations.some((l) => l.toLowerCase().includes(location))) &&
      (!term || p.terms.includes(term)) &&
      p.score >= minScore &&
      (!remote || p.is_remote)
  );
}

function feedStatus(): MockResponse {
  const s = db();
  const seq = statusData.sequence as (FeedStatus & { after_ms: number })[];
  let instant = false;
  try {
    instant = window.localStorage.getItem("step1.mock.instant") === "1";
  } catch {
    // ignore
  }
  // Progress follows the clock, not the number of polls, like a real job would.
  const elapsed = s.buildStartedAt === null || instant ? Infinity : Date.now() - s.buildStartedAt;
  const cur = [...seq].reverse().find((x) => elapsed >= x.after_ms) ?? seq[0];
  if (cur.state === "ready" && s.buildStartedAt !== null) {
    s.buildStartedAt = null;
    persist();
  }
  const body: FeedStatus = { state: cur.state, pct: cur.pct, step: cur.step };
  return ok(body, 200, cur.state === "building" ? { "Retry-After": "1" } : {});
}

type Body = Record<string, unknown> | undefined;

function route(method: string, url: URL, body: Body, token: string | null): MockResponse {
  const s = db();
  const path = url.pathname;
  const q = url.searchParams;

  // ---- auth (no token needed) ----
  if (method === "POST" && (path === "/auth/register" || path === "/auth/login")) {
    const email = String(body?.email ?? "").trim().toLowerCase();
    const password = String(body?.password ?? "");
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return err(422, "Enter a valid email address.");
    if (password.length < 8) {
      return path === "/auth/register"
        ? err(422, "Password must be at least 8 characters.")
        : err(401, "Incorrect email or password.");
    }
    if (path === "/auth/register") {
      if (s.users[email]) return err(409, "An account with that email already exists.");
    }
    // Mock login accepts any email + password >= 8; unknown emails get an account.
    if (!s.users[email]) {
      const name = typeof body?.display_name === "string" ? body.display_name : null;
      s.users[email] = { id: s.nextId++, email, display_name: name };
      persist();
    }
    return ok(authResponse(s.users[email]));
  }

  const user = userFromToken(token);
  if (!user) return err(401, "Not authenticated");
  const email = user.email;

  if (method === "GET" && path === "/me") {
    return ok({ ...user, onboarded: !!s.profiles[email] });
  }

  // ---- profile ----
  if (path === "/profile" && method === "GET") {
    const p = s.profiles[email];
    return p ? ok(p) : err(404, "Profile not found");
  }
  if (path === "/profile" && method === "PUT") {
    const input = body as unknown as ProfileInput;
    const interests = input?.interests ?? [];
    if (interests.length < 3 || interests.length > 5) {
      return err(422, "Pick 3 to 5 fields of interest.");
    }
    if (!input.major?.trim()) return err(422, "Major is required.");
    const prev = s.profiles[email];
    let resume = s.resumes[email] ?? prev?.resume ?? null;
    if (resume && Array.isArray(input.skills)) resume = { ...resume, skills: input.skills };
    const version = (prev?.profile_version ?? 0) + 1;
    s.profiles[email] = {
      school: input.school,
      major: input.major,
      minor: input.minor ?? null,
      degree_level: input.degree_level,
      grad_year: input.grad_year,
      gpa: input.gpa ?? null,
      target_terms: input.target_terms,
      preferred_locations: input.preferred_locations,
      remote_ok: input.remote_ok,
      interests: [...interests]
        .sort((a, b) => a.rank - b.rank)
        .map((i) => ({ role: i.role, label: roleLabel(i.role), rank: i.rank })),
      resume,
      profile_version: version,
    };
    s.buildStartedAt = Date.now();
    persist();
    return ok({ profile_version: version, state: "building" }, 202, { "Retry-After": "1" });
  }
  if (path === "/profile/resume/presign" && method === "POST") {
    const key = `resumes/${user.id}/${Date.now()}.pdf`;
    return ok({
      upload_url: `mock://upload/${key}`,
      key,
      method: "PUT",
      headers: { "Content-Type": "application/pdf" },
    });
  }
  if (path === "/profile/resume/commit" && method === "POST") {
    const filename = String(body?.filename ?? "resume.pdf");
    // A filename containing "scan" simulates an image-only PDF.
    const needs_ocr = /scan/i.test(filename);
    const resume: Resume = {
      filename,
      uploaded_at: nowIso(),
      skills: needs_ocr ? [] : ["Python", "SQL", "Java", "React", "AWS", "Linux", "Git", "Tableau"],
      needs_ocr,
    };
    s.resumes[email] = resume;
    if (s.profiles[email]) s.profiles[email].resume = resume;
    persist();
    return ok(resume);
  }

  // ---- feed ----
  if (path === "/feed/status" && method === "GET") return feedStatus();
  if (path === "/feed" && method === "GET") {
    if (!s.profiles[email]) return err(409, "Complete onboarding first");
    return ok(paginate(sortPostings(filterFeed(q)).map(decorate), q));
  }

  let m = path.match(/^\/postings\/(.+)$/);
  if (m && method === "GET") {
    const p = POSTINGS.find((x) => x.id === decodeURIComponent(m![1]));
    return p ? ok(decorate(p)) : err(404, "Posting not found");
  }

  // ---- saved ----
  if (path === "/saved" && method === "GET") {
    const list = POSTINGS.filter((p) => s.saved.includes(p.id));
    return ok(paginate(sortPostings(list).map(decorate), q));
  }
  m = path.match(/^\/saved\/(.+)$/);
  if (m) {
    const id = decodeURIComponent(m[1]);
    if (!POSTINGS.some((p) => p.id === id)) return err(404, "Posting not found");
    if (method === "POST") {
      if (!s.saved.includes(id)) s.saved.push(id);
      persist();
      return ok(null, 204);
    }
    if (method === "DELETE") {
      s.saved = s.saved.filter((x) => x !== id);
      persist();
      return ok(null, 204);
    }
  }

  // ---- applications ----
  if (path === "/applications" && method === "GET") {
    const items = s.apps.map((a) => {
      const d = appDetail(a);
      return {
        id: d.id,
        posting: d.posting,
        status: d.status,
        applied_at: d.applied_at,
        last_event_at: d.events[d.events.length - 1]?.occurred_at ?? d.applied_at,
      };
    });
    items.sort((a, b) => b.last_event_at.localeCompare(a.last_event_at));
    return ok({ items });
  }
  if (path === "/applications" && method === "POST") {
    const pid = String(body?.posting_id ?? "");
    if (!POSTINGS.some((p) => p.id === pid)) return err(404, "Posting not found");
    if (s.apps.some((a) => a.posting_id === pid)) {
      return err(409, "You already have an application for this posting.");
    }
    const at = typeof body?.applied_at === "string" ? body.applied_at : nowIso();
    const app: MockApp = {
      id: s.nextId++,
      posting_id: pid,
      applied_at: at,
      events: [{ id: s.nextId++, kind: "applied", occurred_at: at, note: null, source: "manual" }],
    };
    s.apps.push(app);
    persist();
    return ok(appDetail(app), 201);
  }
  m = path.match(/^\/applications\/(\d+)(\/events)?$/);
  if (m) {
    const app = s.apps.find((a) => a.id === Number(m![1]));
    if (!app) return err(404, "Application not found");
    if (!m[2] && method === "GET") return ok(appDetail(app));
    if (m[2] && method === "POST") {
      const kind = String(body?.kind ?? "");
      const status = statusOf(app);
      if (kind !== "note" && !(GRAPH[status] ?? []).includes(kind)) {
        return err(409, `Can't record "${kind}" from "${status}".`);
      }
      const note = typeof body?.note === "string" && body.note.trim() ? body.note.trim() : null;
      if (kind === "note" && !note) return err(422, "A note needs some text.");
      app.events.push({
        id: s.nextId++,
        kind,
        occurred_at: typeof body?.occurred_at === "string" ? body.occurred_at : nowIso(),
        note,
        source: "manual",
      });
      persist();
      return ok(appDetail(app), 201);
    }
  }

  return err(404, "Not found");
}

function shouldFail(method: string, path: string): boolean {
  try {
    const rule = window.localStorage.getItem("step1.mock.fail");
    if (rule && `${method} ${path}`.startsWith(rule)) {
      window.localStorage.removeItem("step1.mock.fail");
      return true;
    }
  } catch {
    // ignore
  }
  return false;
}

export async function handle(
  method: string,
  pathAndQuery: string,
  body: unknown,
  token: string | null
): Promise<MockResponse> {
  await sleep(DELAY_MS);
  const url = new URL(pathAndQuery, "http://mock.local");
  if (shouldFail(method, url.pathname)) {
    return err(500, "The server had a problem. Nothing was changed — try again.");
  }
  // Deep-copy so callers can never mutate mock state by reference.
  const res = route(method, url, body as Body, token);
  return { ...res, body: res.body == null ? null : JSON.parse(JSON.stringify(res.body)) };
}

export async function handleUpload(uploadUrl: string, file: File): Promise<void> {
  await sleep(DELAY_MS);
  if (!uploadUrl.startsWith("mock://upload/") || file.size === 0) {
    throw new Error("Upload failed");
  }
}
