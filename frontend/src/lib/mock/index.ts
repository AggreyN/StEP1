// In-browser mock of the StEP1 API. Only src/lib/api.ts imports this.
//
// It speaks HTTP semantics (status, headers, {"detail"} errors) so api.ts runs
// the same code path in both modes. State is seeded from the JSON fixtures,
// kept in memory, and mirrored to localStorage so a page reload (e.g. a
// filtered dashboard URL) sees the same saves/applications.
//
// For tests, every request is also appended to window.__step1Requests
// ("METHOD /path?query"), and its JSON body to window.__step1Bodies under the
// same index, so a spec can check what the client asked for and sent.
//
// Test knobs (localStorage):
//   step1.mock.instant = "1"            GET /feed/status reports `ready` on
//                                       the very first poll
//   step1.mock.stuck = "1"              GET /feed/status never leaves `building`
//   step1.mock.ingest = "stale"         which ingest.json scenario GET
//                                       /ingest/status answers with (fresh,
//                                       running, never, stale, failed, partial,
//                                       manual); "error" makes the route 404,
//                                       like a backend that predates it
//   step1.mock.fail = "POST /saved"     the next request whose "METHOD /path"
//                                       starts with this fails once with a 500.
//                                       "429 POST /auth/login" picks the status;
//                                       "always GET /stats" keeps failing

import feedData from "./feed.json";
import profileData from "./profile.json";
import applicationsData from "./applications.json";
import statusData from "./status.json";
import transitionsData from "./transitions.json";
import ingestData from "./ingest.json";
import statsData from "./stats.json";
import reviewsData from "./reviews.json";
import baseResumeData from "./base-resume.json";
import tailorData from "./tailor.json";
import adminUsersData from "./admin-users.json";
import type {
  ApplicationDetail,
  ApplicationEvent,
  BaseResume,
  PostingKind,
  ResumeDoc,
  ResumeFull,
  FeedStatus,
  IngestStatus,
  Posting,
  Profile,
  ProfileInput,
  Resume,
} from "../types";
import { AUTH_MODE, COGNITO, REGISTRATION_OPEN } from "../config";
import { roleLabel } from "../roles";

const DELAY_MS = 300;
const TAILOR_DELAY_MS = 1700; // plus DELAY_MS: two seconds in all
const STORE_KEY = "step1.mock.v4";
const DEMO_EMAIL = "demo@umd.edu";


const GRAPH = transitionsData.graph as Record<string, string[]>;
const NON_STATUS = new Set(transitionsData.non_status_kinds);
// Keep the fixture's dates relative to today (see feed.json `anchor`), so the
// server-written "Posted 2 days ago" reasons and the dates agree.
const DAY_MS = 86_400_000;
const DRIFT_DAYS = Math.max(0, Math.floor((Date.now() - Date.parse(feedData.anchor)) / DAY_MS));
const POSTINGS = (feedData.items as Posting[]).map((p) => ({
  ...p,
  date_posted: p.date_posted
    ? new Date(Date.parse(p.date_posted) + DRIFT_DAYS * DAY_MS).toISOString().replace(/\.\d+Z$/, "Z")
    : null,
}));

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
/** Everything that belongs to one user. Each user only ever sees their own:
 *  another user's application id is a 404, as it is on the real API. */
interface Account {
  saved: string[];
  apps: MockApp[];
  buildStartedAt: number | null; // null = not building
  /** The last step a poll reported during this build, and when (mock only). */
  buildShown?: number;
  buildShownAt?: number;
  /** Fingerprint of the password last used to sign in (see `fingerprint`). */
  pw: string | null;
  /** The base resume, once saved. */
  base?: BaseResume;
  /** Saved tailored resumes. */
  resumes?: ResumeFull[];
}
interface State {
  users: Record<string, MockUser>;
  profiles: Record<string, Profile>;
  resumes: Record<string, Resume>;
  accounts: Record<string, Account>;
  /** Reviews written in this browser, newest last. The fixture's come after them in the admin list. */
  reviews?: MockReview[];
  nextId: number;
}

interface MockReview {
  id: number;
  rating: number;
  body: string;
  created_at: string;
  user: { email: string; display_name: string | null } | null;
}

/** demo@umd.edu stands in for the owner. */
const isAdmin = (email: string) => email === DEMO_EMAIL;

function allReviews(): MockReview[] {
  const HOUR = 3_600_000;
  const now = Date.now();
  const fixture = (reviewsData.items as (Omit<MockReview, "created_at"> & { created_hours_ago: number })[]).map(
    ({ created_hours_ago, ...r }) => ({
      ...r,
      created_at: new Date(now - created_hours_ago * HOUR).toISOString().replace(/\.\d+Z$/, "Z"),
    })
  );
  const mine = [...(db().reviews ?? [])].reverse();
  return [...mine, ...fixture];
}

function seed(): State {
  return {
    users: { [DEMO_EMAIL]: { id: 1, email: DEMO_EMAIL, display_name: "Demo Terp" } },
    profiles: { [DEMO_EMAIL]: profileData as Profile },
    resumes: {},
    accounts: {},
    nextId: 100,
  };
}

/** A user's own data. New accounts start from a copy of the fixtures, so the
 *  Saved and Applications screens have something in them. */
function account(email: string): Account {
  const s = db();
  if (!s.accounts[email]) {
    s.accounts[email] = {
      saved: POSTINGS.filter((p) => p.saved).map((p) => p.id),
      apps: JSON.parse(JSON.stringify(applicationsData.items)) as MockApp[],
      buildStartedAt: null,
      pw: null,
    };
  }
  return s.accounts[email];
}

/** The mock never stores a password. It keeps a short, one-way fingerprint so
 *  DELETE /me can tell a wrong password from the right one. Not security:
 *  these are fake accounts in your own browser. */
function fingerprint(password: string): string {
  let h = 5381;
  for (let i = 0; i < password.length; i++) h = ((h << 5) + h + password.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
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

/** Cognito mode: the bearer token is Cognito's ID token. The mock checks
 *  what the real API checks, except the signature: the audience, the token
 *  use and the expiry. It then finds or creates the user by email, as the
 *  API does on first sight of a new Cognito user. */
function userFromIdToken(token: string): MockUser | null {
  try {
    const part = token.split(".")[1];
    const binary = atob(part.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(part.length / 4) * 4, "="));
    const claims = JSON.parse(new TextDecoder().decode(Uint8Array.from(binary, (c) => c.charCodeAt(0))));
    const audience = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
    if (claims.token_use !== "id" || !audience.includes(COGNITO.clientId)) return null;
    if (typeof claims.exp !== "number" || claims.exp * 1000 <= Date.now()) return null;
    const email = String(claims.email ?? `${claims.sub}@cognito.local`).toLowerCase();
    const s = db();
    if (!s.users[email]) {
      s.users[email] = { id: s.nextId++, email, display_name: typeof claims.name === "string" ? claims.name : null };
      persist();
    }
    return s.users[email];
  } catch {
    return null;
  }
}

function userFromToken(token: string | null): MockUser | null {
  if (AUTH_MODE === "cognito") return token ? userFromIdToken(token) : null;
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

function decorate(p: Posting, mine: Account): Posting {
  const app = mine.apps.find((a) => a.posting_id === p.id);
  return {
    ...p,
    saved: mine.saved.includes(p.id),
    application: app ? { id: app.id, status: statusOf(app) } : null,
  };
}

function appDetail(app: MockApp, mine: Account): ApplicationDetail {
  const posting = POSTINGS.find((p) => p.id === app.posting_id)!;
  const status = statusOf(app);
  return {
    id: app.id,
    posting: decorate(posting, mine),
    status,
    applied_at: app.applied_at,
    events: [...app.events].sort((a, b) => a.occurred_at.localeCompare(b.occurred_at)),
    next_transitions: GRAPH[status] ?? [],
  };
}

// Newest first with undated postings last (an empty string sorts below any
// ISO date), and highest score first.
const byDate = (a: Posting, b: Posting) => (b.date_posted ?? "").localeCompare(a.date_posted ?? "");
const byScore = (a: Posting, b: Posting) => (b.score ?? -1) - (a.score ?? -1);
const byId = (a: Posting, b: Posting) => a.id.localeCompare(b.id);

/** recent: date, then score, then id.  score: score, then date, then id. */
function sortPostings(list: Posting[], sort: "recent" | "score" = "score"): Posting[] {
  const [first, second] = sort === "recent" ? [byDate, byScore] : [byScore, byDate];
  return [...list].sort((a, b) => first(a, b) || second(a, b) || byId(a, b));
}

function paginate(list: Posting[], q: URLSearchParams) {
  const page = Math.max(1, Number(q.get("page")) || 1);
  const size = Math.min(100, Math.max(1, Number(q.get("page_size")) || 20));
  const items = list.slice((page - 1) * size, page * size);
  return { items, page, total: list.length, has_more: page * size < list.length };
}

/** Same filter semantics the real /feed applies. */
/** The feed only shows the kinds of role the profile asks for, like the
 *  other hard filters (terms, degree); `kind` narrows it further. */
function filterFeed(q: URLSearchParams, lookingFor: PostingKind[]): Posting[] {
  const kind = q.get("kind");
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
      (p.score ?? 0) >= minScore &&
      (!remote || p.is_remote) &&
      lookingFor.includes(p.kind) &&
      (!kind || p.kind === kind)
  );
}

function feedStatus(mine: Account): MockResponse {
  const seq = statusData.sequence as (FeedStatus & { after_ms: number })[];
  let instant = false;
  let stuck = false;
  try {
    instant = window.localStorage.getItem("step1.mock.instant") === "1";
    stuck = window.localStorage.getItem("step1.mock.stuck") === "1";
  } catch {
    // ignore
  }
  if (stuck) {
    const { state, pct, step } = seq.filter((x) => x.state === "building").slice(-1)[0];
    return ok({ state, pct, step }, 200, { "Retry-After": "1" });
  }
  // Progress follows the clock, like a real job would, but a poll never
  // skips a step: a slow poll (a busy machine) would otherwise jump from the
  // first step straight to ready and the middle step would never be shown.
  const elapsed = mine.buildStartedAt === null || instant ? Infinity : Date.now() - mine.buildStartedAt;
  const byClock = seq.findLastIndex((x) => elapsed >= x.after_ms);
  // A step also stays put for a moment once shown, so that two polls made
  // together (React runs effects twice in development) both see it.
  const shown = mine.buildShown ?? -1;
  const settled = Date.now() - (mine.buildShownAt ?? 0) >= 400;
  let index =
    mine.buildStartedAt === null || instant ? seq.length - 1 : Math.min(Math.max(byClock, 0), shown + 1);
  if (index > shown && shown >= 0 && !settled && !instant) index = shown;
  const cur = seq[index];
  if (index !== shown) mine.buildShownAt = Date.now();
  mine.buildShown = index;
  if (cur.state === "ready" && mine.buildStartedAt !== null) mine.buildStartedAt = null;
  persist();
  const body: FeedStatus = { state: cur.state, pct: cur.pct, step: cur.step };
  return ok(body, 200, cur.state === "building" ? { "Retry-After": "1" } : {});
}

interface IngestScenario {
  last_success_hours_ago: number | null;
  interval_hours: number;
  auto: boolean;
  running: boolean;
  active_postings: number;
  sources: {
    source: string;
    last_success_hours_ago: number | null;
    last_attempt_hours_ago: number | null;
    fetched: number;
    upserted: number;
    deactivated: number;
    error: string | null;
  }[];
}

function ingestStatus(): MockResponse {
  let pick: string = ingestData.default;
  try {
    pick = window.localStorage.getItem("step1.mock.ingest") || pick;
  } catch {
    // ignore
  }
  const sc = (ingestData.scenarios as Record<string, IngestScenario>)[pick];
  if (!sc) return err(404, "Not Found");
  const HOUR = 3_600_000;
  const now = Date.now();
  const at = (hoursAgo: number | null) =>
    hoursAgo === null ? null : new Date(now - hoursAgo * HOUR).toISOString().replace(/\.\d+Z$/, "Z");
  const last = at(sc.last_success_hours_ago);
  const body: IngestStatus = {
    last_success_at: last,
    next_due_at:
      sc.auto && sc.last_success_hours_ago !== null
        ? at(sc.last_success_hours_ago - sc.interval_hours)
        : null,
    interval_hours: sc.interval_hours,
    auto: sc.auto,
    running: sc.running,
    active_postings: sc.active_postings,
    sources: sc.sources.map((x) => ({
      source: x.source,
      last_success_at: at(x.last_success_hours_ago),
      last_attempt_at: at(x.last_attempt_hours_ago),
      fetched: x.fetched,
      upserted: x.upserted,
      deactivated: x.deactivated,
      error: x.error,
    })),
  };
  return ok(body);
}

type Body = Record<string, unknown> | undefined;

function route(method: string, url: URL, body: Body, token: string | null): MockResponse {
  const s = db();
  const path = url.pathname;
  const q = url.searchParams;

  // ---- auth (no token needed) ----
  if (method === "POST" && (path === "/auth/register" || path === "/auth/login")) {
    if (AUTH_MODE === "cognito") {
      return err(404, path === "/auth/register" ? "Registration is handled by Cognito." : "Login is handled by Cognito.");
    }
    if (path === "/auth/register" && !REGISTRATION_OPEN) return err(403, "Registration is closed.");
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
    // Mock login accepts any email + password >= 8; unknown emails get an
    // account. With registration closed only people who already have one
    // can sign in.
    if (!s.users[email] && !REGISTRATION_OPEN) return err(401, "Incorrect email or password.");
    if (!s.users[email]) {
      const name = typeof body?.display_name === "string" ? body.display_name : null;
      s.users[email] = { id: s.nextId++, email, display_name: name };
      persist();
    }
    account(email).pw = fingerprint(password);
    persist();
    return ok(authResponse(s.users[email]));
  }

  // ---- public ----
  if (method === "GET" && path === "/stats") {
    const { updated_hours_ago, ...counts } = statsData.stats;
    return ok({
      ...counts,
      updated_at: new Date(Date.now() - updated_hours_ago * 3_600_000).toISOString().replace(/\.\d+Z$/, "Z"),
    });
  }

  const user = userFromToken(token);
  if (!user) return err(401, "Not authenticated");
  const email = user.email;
  const mine = account(email);

  if (method === "GET" && path === "/me") {
    return ok({ ...user, onboarded: !!s.profiles[email], is_admin: isAdmin(email) });
  }
  // ---- reviews ----
  if (method === "POST" && path === "/reviews") {
    const rating = body?.rating;
    const text = typeof body?.body === "string" ? body.body.trim() : "";
    if (!Number.isInteger(rating) || (rating as number) < 1 || (rating as number) > 5) {
      return err(422, "rating: Choose a rating from 1 to 5.");
    }
    if (!text) return err(422, "body: Write a few words.");
    if (text.length > 2000) return err(422, "body: A review can be at most 2000 characters.");
    const review: MockReview = {
      id: s.nextId++,
      rating: rating as number,
      body: text,
      created_at: nowIso().replace(/\.\d+Z$/, "Z"),
      user: { email: user.email, display_name: user.display_name },
    };
    s.reviews = [...(s.reviews ?? []), review];
    persist();
    return ok({ id: review.id, rating: review.rating, body: review.body, created_at: review.created_at }, 201);
  }
  if (method === "GET" && path === "/admin/reviews") {
    if (!isAdmin(email)) return err(404, "Not found.");
    const all = allReviews();
    const page = Math.max(1, Number(q.get("page")) || 1);
    const size = Math.min(100, Math.max(1, Number(q.get("page_size")) || 20));
    const average = all.length ? all.reduce((n, r) => n + r.rating, 0) / all.length : null;
    return ok({
      items: all.slice((page - 1) * size, page * size),
      page,
      total: all.length,
      has_more: page * size < all.length,
      average_rating: average === null ? null : Math.round(average * 100) / 100,
    });
  }

  if (method === "DELETE" && path === "/me") {
    if (AUTH_MODE !== "cognito") {
      const password = String(body?.password ?? "");
      if (!password) return err(422, "password: Field required");
      if (fingerprint(password) !== mine.pw) return err(403, "Password is incorrect.");
    }
    // Everything that belonged to this user goes: account, profile, resume,
    // saved postings, applications and their events.
    // Their reviews stay, but no longer say who wrote them.
    s.reviews = (s.reviews ?? []).map((r) => (r.user?.email === email ? { ...r, user: null } : r));
    delete s.users[email];
    delete s.profiles[email];
    delete s.resumes[email];
    delete s.accounts[email];
    persist();
    return ok(null, 204);
  }

  // ---- profile ----
  if (path === "/profile" && method === "GET") {
    const p = s.profiles[email];
    return p ? ok({ ...p, looking_for: p.looking_for?.length ? p.looking_for : ["internship"] }) : err(404, "Profile not found");
  }
  if (path === "/profile" && method === "PUT") {
    const input = body as unknown as ProfileInput;
    const interests = input?.interests ?? [];
    if (interests.length < 3 || interests.length > 5) {
      return err(422, "Pick 3 to 5 fields of interest.");
    }
    if (!input.major?.trim()) return err(422, "Major is required.");
    const lookingFor = Array.isArray(input.looking_for)
      ? input.looking_for.filter((k): k is PostingKind => k === "internship" || k === "new_grad")
      : [];
    if (!lookingFor.length) return err(422, "looking_for: Choose internships, new grad roles, or both.");
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
      looking_for: [...new Set(lookingFor)],
      profile_version: version,
    };
    mine.buildStartedAt = Date.now();
    mine.buildShown = -1;
    persist();
    return ok({ profile_version: version, state: "building" }, 202, { "Retry-After": "1" });
  }
  if (path === "/profile/resume/presign" && method === "POST") {
    const size = Number(body?.size);
    const name = String(body?.filename ?? "");
    if (body?.content_type !== "application/pdf" || !/\.pdf$/i.test(name)) {
      return err(422, "Resumes must be PDF files (up to 5 MB).");
    }
    if (!Number.isInteger(size)) return err(422, "size: Field required");
    if (size < 1024 || size > 5 * 1024 * 1024) return err(422, "Resumes must be between 1 KB and 5 MB.");
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
    // A filename containing "notpdf" simulates a file whose contents are not
    // a PDF, which only the server can tell.
    if (/notpdf/i.test(filename)) return err(400, "That file isn't a PDF.");
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

  if (path === "/ingest/status" && method === "GET") return ingestStatus();

  // ---- feed ----
  if (path === "/feed/status" && method === "GET") return feedStatus(mine);
  if (path === "/feed" && method === "GET") {
    if (!s.profiles[email]) return err(409, "Complete onboarding first");
    const sort = q.get("sort") ?? "recent"; // the API's default
    if (sort !== "recent" && sort !== "score") return err(422, "sort: must be 'recent' or 'score'");
    const lookingFor = s.profiles[email].looking_for?.length ? s.profiles[email].looking_for : (["internship"] as PostingKind[]);
    return ok(paginate(sortPostings(filterFeed(q, lookingFor), sort).map((p) => decorate(p, mine)), q));
  }

  let m = path.match(/^\/postings\/(.+)$/);
  if (m && method === "GET") {
    const p = POSTINGS.find((x) => x.id === decodeURIComponent(m![1]));
    return p ? ok(decorate(p, mine)) : err(404, "Posting not found");
  }

  // ---- saved ----
  if (path === "/saved" && method === "GET") {
    const list = POSTINGS.filter((p) => mine.saved.includes(p.id));
    return ok(paginate(sortPostings(list).map((p) => decorate(p, mine)), q));
  }
  m = path.match(/^\/saved\/(.+)$/);
  if (m) {
    const id = decodeURIComponent(m[1]);
    if (!POSTINGS.some((p) => p.id === id)) return err(404, "Posting not found");
    if (method === "POST") {
      if (!mine.saved.includes(id)) mine.saved.push(id);
      persist();
      return ok(null, 204);
    }
    if (method === "DELETE") {
      mine.saved = mine.saved.filter((x) => x !== id);
      persist();
      return ok(null, 204);
    }
  }

  // ---- applications ----
  if (path === "/applications" && method === "GET") {
    const items = mine.apps.map((a) => {
      const d = appDetail(a, mine);
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
    if (mine.apps.some((a) => a.posting_id === pid)) {
      return err(409, "You already have an application for this posting.");
    }
    const at = typeof body?.applied_at === "string" ? body.applied_at : nowIso();
    const app: MockApp = {
      id: s.nextId++,
      posting_id: pid,
      applied_at: at,
      events: [{ id: s.nextId++, kind: "applied", occurred_at: at, note: null, source: "manual" }],
    };
    mine.apps.push(app);
    persist();
    return ok(appDetail(app, mine), 201);
  }
  m = path.match(/^\/applications\/(\d+)(\/events)?$/);
  if (m) {
    const app = mine.apps.find((a) => a.id === Number(m![1]));
    if (!app) return err(404, "Application not found");
    if (!m[2] && method === "GET") return ok(appDetail(app, mine));
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
      return ok(appDetail(app, mine), 201);
    }
  }

  const extra = resumeRoutes(method, path, q, body, email, mine) ?? adminUserRoutes(method, path, q, email);
  if (extra) return extra;

  return err(404, "Not found");
}

// ---------- resumes ----------

const iso = (ms = Date.now()) => new Date(ms).toISOString().replace(/\.\d+Z$/, "Z");
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));

function baseFixture(): BaseResume {
  const { _comment, ...b } = baseResumeData as BaseResume & { _comment?: string };
  void _comment;
  return clone(b);
}

/** The canned tailored draft: the base with Projects moved up and Skills trimmed. */
function draftFrom(base: BaseResume, forPosting: boolean): ResumeDoc {
  const doc: ResumeDoc = { name: base.name, contact: [...base.contact], sections: clone(base.sections) };
  if (forPosting) {
    const i = doc.sections.findIndex((x) => x.title === "Projects");
    if (i > 0) doc.sections.splice(1, 0, ...doc.sections.splice(i, 1));
  }
  const skills = doc.sections.find((x) => x.title === "Skills");
  if (skills?.entries[0]) skills.entries[0].lines = skills.entries[0].lines.map((l) => l.replace(", Tutoring", ""));
  return doc;
}

function validDoc(doc: unknown): doc is ResumeDoc {
  const d = doc as ResumeDoc;
  return !!d && typeof d.name === "string" && Array.isArray(d.contact) && Array.isArray(d.sections);
}

function summaryOf(r: ResumeFull) {
  const { doc, ...summary } = r;
  void doc;
  return summary;
}

function resumeRoutes(
  method: string,
  path: string,
  q: URLSearchParams,
  body: Body,
  email: string,
  mine: Account
): MockResponse | null {
  const s = db();
  if (path === "/resume/base/extract" && method === "POST") {
    if (!s.resumes[email] && !s.profiles[email]?.resume) return err(409, "Upload your resume first.");
    return ok(baseFixture());
  }
  if (path === "/resume/base" && method === "GET") {
    return mine.base ? ok(mine.base) : err(404, "No base resume yet.");
  }
  if (path === "/resume/base" && method === "PUT") {
    const b = body as unknown as BaseResume;
    if (!validDoc(b) || !Array.isArray(b.skill_inventory)) return err(422, "body: A resume needs a name, contact lines and sections.");
    if (!b.name.trim()) return err(422, "name: Add your name.");
    mine.base = clone(b);
    persist();
    return ok(mine.base);
  }
  if (path === "/tailor" && method === "POST") {
    const postingId = typeof body?.posting_id === "string" ? body.posting_id : undefined;
    const jobText = typeof body?.job_text === "string" ? body.job_text : undefined;
    if ((postingId === undefined) === (jobText === undefined)) {
      return err(422, "Give either a posting or the text of a job description, not both.");
    }
    if (jobText !== undefined && !jobText.trim()) return err(422, "job_text: Paste the job description.");
    if (jobText !== undefined && jobText.length > 20000) return err(422, "job_text: A job description can be at most 20000 characters.");
    if (!mine.base) return err(409, "Set up your base resume first.");
    if (postingId !== undefined) {
      const posting = POSTINGS.find((p) => p.id === postingId);
      if (!posting) return err(404, "Posting not found");
      const t = tailorData.posting;
      return ok({
        draft: draftFrom(mine.base, true),
        report: { fit: t.fit, changes: t.changes, gaps: t.gaps, question: t.question },
        suggested_name: `${posting.company.name}, ${posting.title}`.slice(0, 80),
      });
    }
    const t = tailorData.text;
    return ok({
      draft: draftFrom(mine.base, false),
      report: { fit: t.fit, changes: t.changes, gaps: t.gaps, question: t.question },
      suggested_name: "Tailored resume",
    });
  }
  if (path === "/resumes" && method === "GET") {
    const items = [...(mine.resumes ?? [])].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).map(summaryOf);
    return ok({ items });
  }
  if (path === "/resumes" && method === "POST") {
    const name = typeof body?.name === "string" ? body.name.trim() : "";
    if (!name || name.length > 80) return err(422, "name: Give it a name of 1 to 80 characters.");
    if (!validDoc(body?.doc)) return err(422, "doc: A resume needs a name, contact lines and sections.");
    const postingId = typeof body?.posting_id === "string" ? body.posting_id : null;
    const posting = postingId ? POSTINGS.find((p) => p.id === postingId) : null;
    if (postingId && !posting) return err(404, "Posting not found");
    const now = iso();
    const r: ResumeFull = {
      id: s.nextId++,
      name,
      created_at: now,
      updated_at: now,
      posting: posting ? { id: posting.id, title: posting.title, company: posting.company.name } : null,
      doc: clone(body!.doc as ResumeDoc),
    };
    mine.resumes = [...(mine.resumes ?? []), r];
    persist();
    return ok(r, 201);
  }
  const m = path.match(/^\/resumes\/(\d+)(\/download)?$/);
  if (m) {
    const r = (mine.resumes ?? []).find((x) => x.id === Number(m[1]));
    if (!r) return err(404, "Resume not found");
    if (m[2] && method === "GET") {
      const format = q.get("format");
      if (format !== "pdf" && format !== "docx") return err(422, "format: pdf or docx");
      const filename = `${r.doc.name.replace(/\s+/g, "_")}_${r.name.replace(/[^\w]+/g, "_").replace(/^_|_$/g, "")}.${format}`;
      const type =
        format === "pdf" ? "application/pdf" : "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
      const text = format === "pdf" ? `%PDF-1.4\n% placeholder for ${r.name}\n%%EOF\n` : `placeholder DOCX for ${r.name}`;
      return ok(new Blob([text], { type }), 200, {
        "Content-Type": type,
        "Content-Disposition": `attachment; filename="${filename}"`,
      });
    }
    if (!m[2] && method === "GET") return ok(r);
    if (!m[2] && method === "PUT") {
      if (body?.name !== undefined) {
        const name = typeof body.name === "string" ? body.name.trim() : "";
        if (!name || name.length > 80) return err(422, "name: Give it a name of 1 to 80 characters.");
        r.name = name;
      }
      if (body?.doc !== undefined) {
        if (!validDoc(body.doc)) return err(422, "doc: A resume needs a name, contact lines and sections.");
        r.doc = clone(body.doc as ResumeDoc);
      }
      r.updated_at = iso();
      persist();
      return ok(r);
    }
    if (!m[2] && method === "DELETE") {
      mine.resumes = (mine.resumes ?? []).filter((x) => x.id !== r.id);
      persist();
      return ok(null, 204);
    }
  }
  return null;
}

// ---------- admin: people ----------

interface FixturePerson {
  id: number;
  email: string;
  display_name: string | null;
  created_days_ago: number;
  onboarded: boolean;
  school: string | null;
  major: string | null;
  grad_year: number | null;
  applications: number;
  saved: number;
  tailored_resumes: number;
  has_resume: boolean;
  last_active_hours_ago: number | null;
}

/** Everyone the admin can see: accounts made in this browser, then the
 *  fictional students in admin-users.json. */
function people() {
  const s = db();
  const HOUR = 3_600_000;
  const live = Object.values(s.users).map((u) => {
    const acc = s.accounts[u.email];
    const prof = s.profiles[u.email];
    return {
      id: u.id,
      email: u.email,
      display_name: u.display_name,
      created_at: iso(Date.now() - 30 * 24 * HOUR),
      onboarded: !!prof,
      school: prof?.school ?? null,
      major: prof?.major ?? null,
      grad_year: prof?.grad_year ?? null,
      applications: acc?.apps.length ?? 0,
      saved: acc?.saved.length ?? 0,
      tailored_resumes: acc?.resumes?.length ?? 0,
      has_resume: !!(s.resumes[u.email] ?? prof?.resume),
      last_active_at: iso(),
      live: true as const,
    };
  });
  const fixture = (adminUsersData.items as FixturePerson[]).map(({ created_days_ago, last_active_hours_ago, ...p }) => ({
    ...p,
    created_at: iso(Date.now() - created_days_ago * 24 * HOUR),
    last_active_at: last_active_hours_ago === null ? null : iso(Date.now() - last_active_hours_ago * HOUR),
    live: false as const,
  }));
  return [...live, ...fixture];
}

function adminUserRoutes(method: string, path: string, q: URLSearchParams, email: string): MockResponse | null {
  if (!path.startsWith("/admin/users")) return null;
  if (!isAdmin(email)) return err(404, "Not found.");
  const s = db();
  if (path === "/admin/users" && method === "GET") {
    const term = (q.get("q") ?? "").trim().toLowerCase();
    const all = people()
      .filter(
        (p) =>
          !term ||
          [p.email, p.display_name ?? "", p.school ?? "", p.major ?? ""].some((v) => v.toLowerCase().includes(term))
      )
      .map(({ live, ...row }) => {
        void live;
        return row;
      });
    const page = Math.max(1, Number(q.get("page")) || 1);
    const size = Math.min(100, Math.max(1, Number(q.get("page_size")) || 20));
    return ok({ items: all.slice((page - 1) * size, page * size), page, total: all.length, has_more: page * size < all.length });
  }
  const m = path.match(/^\/admin\/users\/(\d+)(\/resume-file)?$/);
  if (!m || method !== "GET") return null;
  const person = people().find((p) => p.id === Number(m[1]));
  if (!person) return err(404, "Not found.");
  if (m[2]) {
    if (!person.has_resume) return err(404, "This person hasn't uploaded a resume.");
    const filename = s.resumes[person.email]?.filename ?? s.profiles[person.email]?.resume?.filename ?? "resume.pdf";
    const blob = new Blob([`%PDF-1.4\n% placeholder for ${person.email}\n%%EOF\n`], { type: "application/pdf" });
    return ok({ url: URL.createObjectURL(blob), filename, expires_at: iso(Date.now() + 5 * 60_000) });
  }
  if (person.live) {
    const acc = account(person.email);
    const prof = s.profiles[person.email] ?? null;
    return ok({
      user: { id: person.id, email: person.email, display_name: person.display_name, created_at: person.created_at, is_admin: isAdmin(person.email) },
      profile: prof && { ...prof, looking_for: prof.looking_for?.length ? prof.looking_for : ["internship"] },
      saved: POSTINGS.filter((p) => acc.saved.includes(p.id)).map((p) => decorate(p, acc)),
      applications: acc.apps.map((a) => appDetail(a, acc)),
      resumes: (acc.resumes ?? []).map(summaryOf),
      reviews: (s.reviews ?? [])
        .filter((r) => r.user?.email === person.email)
        .map(({ user, ...r }) => {
          void user;
          return r;
        }),
    });
  }
  // A fictional student: a plausible profile and a little activity, made up on the spot.
  const acc: Account = { saved: POSTINGS.slice(0, person.saved).map((p) => p.id), apps: [], buildStartedAt: null, pw: null };
  return ok({
    user: { id: person.id, email: person.email, display_name: person.display_name, created_at: person.created_at, is_admin: false },
    profile: person.onboarded
      ? {
          ...(profileData as Profile),
          school: person.school,
          major: person.major,
          minor: null,
          grad_year: person.grad_year,
          resume: person.has_resume ? { filename: "resume.pdf", uploaded_at: person.created_at, skills: ["Python", "SQL"], needs_ocr: false } : null,
          looking_for: ["internship"],
        }
      : null,
    saved: POSTINGS.slice(0, Math.min(person.saved, 5)).map((p) => decorate(p, acc)),
    applications: [],
    resumes: Array.from({ length: person.tailored_resumes }, (_, i) => ({
      id: person.id * 10 + i,
      name: `${POSTINGS[i].company.name}, ${POSTINGS[i].title}`,
      created_at: person.created_at,
      updated_at: person.created_at,
      posting: { id: POSTINGS[i].id, title: POSTINGS[i].title, company: POSTINGS[i].company.name },
    })),
    reviews: [],
  });
}

function record(line: string, body: unknown) {
  const w = window as unknown as { __step1Requests?: string[]; __step1Bodies?: unknown[] };
  w.__step1Requests = [...(w.__step1Requests ?? []).slice(-199), line];
  // Passwords are never kept, even here.
  const safe =
    body && typeof body === "object" && "password" in body ? { ...body, password: "[not recorded]" } : (body ?? null);
  w.__step1Bodies = [...(w.__step1Bodies ?? []).slice(-199), safe];
}

/** Reads the step1.mock.fail knob: "[status] [always] METHOD /path".
 *  Without "always" the rule is used up by the first request it matches. */
function forcedFailure(method: string, path: string): MockResponse | null {
  try {
    const raw = window.localStorage.getItem("step1.mock.fail");
    if (!raw) return null;
    const m = raw.match(/^(?:(\d{3})\s+)?(?:(always)\s+)?(\S+ \S+)$/);
    if (!m || !`${method} ${path}`.startsWith(m[3])) return null;
    if (!m[2]) window.localStorage.removeItem("step1.mock.fail");
    const status = m[1] ? Number(m[1]) : 500;
    if (status === 429) {
      const detail =
        path === "/reviews"
          ? "You've sent a lot of reviews today. Try again tomorrow."
          : path === "/tailor"
            ? "You've tailored a lot of resumes today. Try again tomorrow."
            : "Too many attempts. Wait a minute and try again.";
      return ok({ detail }, 429, { "Retry-After": "60" });
    }
    if (status === 409 && path === "/resume/base/extract") return err(409, "Upload your resume first.");
    if (status === 409 && path === "/tailor") return err(409, "Set up your base resume first.");
    if (status === 503 && path === "/tailor") {
      return err(503, "The resume writer is busy right now. Try again in a few minutes.");
    }
    return err(status, "The server had a problem. Nothing was changed. Try again.");
  } catch {
    return null;
  }
}

export async function handle(
  method: string,
  pathAndQuery: string,
  body: unknown,
  token: string | null
): Promise<MockResponse> {
  await sleep(DELAY_MS);
  const url = new URL(pathAndQuery, "http://mock.local");
  record(`${method} ${url.pathname}${url.search}`, body);
  // Tailoring is slow for real (10 to 40 seconds); two seconds here.
  if (url.pathname === "/tailor") await sleep(TAILOR_DELAY_MS);
  const forced = forcedFailure(method, url.pathname);
  if (forced) return forced;
  // Deep-copy so callers can never mutate mock state by reference.
  const res = route(method, url, body as Body, token);
  if (res.body instanceof Blob) return res;
  return { ...res, body: res.body == null ? null : JSON.parse(JSON.stringify(res.body)) };
}

export async function handleUpload(uploadUrl: string, file: File): Promise<void> {
  await sleep(DELAY_MS);
  if (!uploadUrl.startsWith("mock://upload/") || file.size === 0) {
    throw new Error("Upload failed");
  }
}
