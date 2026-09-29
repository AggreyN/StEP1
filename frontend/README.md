# StEP1 frontend

Internship discovery and application tracking. Next.js (App Router) +
TypeScript + Tailwind, tested with Playwright.

Design and API contract: [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)
(§5 API, §6 timeline) and [`../FRONTEND_BRIEF.md`](../FRONTEND_BRIEF.md).

## Run it

```bash
cd frontend
npm install
```

### Against the mock API (no backend needed)

```bash
NEXT_PUBLIC_API_BASE=mock npm run dev      # http://localhost:3000
```

Sign in with any email and a password of 8+ characters.

- `demo@umd.edu` already has a profile and lands on the dashboard.
- Any other email is a new student and starts at onboarding.

Mock data lives in memory and is mirrored to `localStorage` so a reload keeps
your saves and applications. To reset it, clear site data (or remove the
`step1.mock.v2` key).

### Against the real API

```bash
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
```

or copy `.env.example` to `.env.local` and edit it. The backend must allow
the frontend's origin in CORS (it defaults to `http://localhost:3000`) and
expose the `Retry-After` header.

`NEXT_PUBLIC_API_BASE` is read at build time. If it is unset the app falls
back to the mock API and logs a warning in the browser console.

## Test

```bash
npx playwright install chromium   # once
npm test                          # whole suite
npm test -- --project=mobile      # 375px checks only
npm run lint
npm run typecheck
npm run build
```

The suite always runs against the mock API. It starts its own dev server on
**port 3100** with its own build directory (`.next-test`), so it never reuses
or overwrites whatever is being served on port 3000.

If you run `next start` on port 3000, remember that the API base is baked in
at build time: build with the base you intend to serve
(`NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run build`). To make a
throwaway build without touching `.next`, set `NEXT_DIST_DIR`:

```bash
NEXT_DIST_DIR=.next-check NEXT_PUBLIC_API_BASE=mock npm run build
```

Screenshots of every screen, light and dark, desktop and 375px, including
the dashboard in both sort orders and with the freshness warning:

```bash
SCREENSHOT_DIR=/tmp/step1-screens npm test -- screens
```

## Layout

```
src/
  app/                     one folder per route
    login/                 sign in / register
    onboarding/            profile form, ranked interests, resume upload
    onboarding/building/   polls /feed/status until ready
    page.tsx               dashboard: feed, sort, filters, freshness line
    saved/
    applications/          list grouped by status
    applications/[id]/     timeline
  components/              cards, filter panel, ranker, timeline, dialogs
  lib/
    api.ts                 the only module that talks to a backend
    auth.ts                token storage + useRequireAuth (swap for Cognito here)
    types.ts               the API contract, hand-written
    roles.ts               the 14 role keys and labels (mirrors backend roles.py)
    labels.ts              display labels for statuses, terms, degree levels
    filters.ts             filters and sort <-> URL, empty-state diagnosis
    freshness.ts           wording rules for the "listings updated…" line
    format.ts              dates, salary
    mock/                  in-browser API used when NEXT_PUBLIC_API_BASE=mock
tests/                     Playwright specs
```

## The dashboard

**Order.** Newest first by default; "Best match" sorts by score. Score badges
and reason chips are on every card either way.

| Sort | URL | Sent to the API | Order |
|---|---|---|---|
| Newest first (default) | no `sort` param | `sort=recent` | date posted, newest first, undated last; then score; then id |
| Best match | `?sort=score` | `sort=score` | score, highest first; then date posted; then id |

The client sends `sort` on every `GET /feed`, including the one-row probes
behind the empty state, so what is on screen never depends on the server's
default. Changing the sort starts again at page 1. An unrecognised `sort` in
the URL is treated as the default.

**Freshness.** One line under the heading, from `GET /ingest/status`:

| Situation | Line | Look |
|---|---|---|
| Normal | Listings updated 3 hours ago · refreshes every 24 hours | quiet grey |
| `auto` is false | Listings updated 3 hours ago | quiet grey |
| `running` is true | Updating listings now… | grey, checked again every 20 s |
| `last_success_at` is null | Listings haven't been loaded yet | quiet grey |
| Older than 2 × `interval_hours` | Listings last updated 3 days ago · a refresh is overdue | amber note |
| Every source has an `error` | Listings last updated 3 days ago · the last refresh failed | amber note |
| Some sources have an `error` | Listings last updated 3 hours ago · part of the last refresh failed | amber note |
| The endpoint fails or doesn't exist | nothing | the dashboard is unaffected |

Hovering the line shows the exact times, the number of open listings, and any
source error. The wording rules are in `src/lib/freshness.ts`.

### Rules the code follows

- **Every request goes through `src/lib/api.ts`.** Components never import
  mock data; `grep -ri mock src/components` returns nothing.
- **The application state graph is not in the app.** The timeline renders its
  buttons from the `next_transitions` array the API returns. `labels.ts` maps
  identifiers to display text and nothing more.
- **Filters and sort are URL query params**, so a view can be linked and
  survives a reload.
- **Errors show the API's `detail` text.**

### About `src/lib/mock/`

Test fixture data, not application logic. It exists so the UI can be built
and tested before (and without) the backend, and it answers with the same
status codes, headers and bodies as the real API.

| File | What it is |
|---|---|
| `feed.json` | 52 postings across all 14 roles, scores 22–95, two of them undated. `anchor` is the day the dates were written against; the mock shifts them so they stay relative to today |
| `ingest.json` | scenarios for `/ingest/status` (fresh, running, never, stale, failed, partial, manual), with times as hours-ago that the mock turns into timestamps |
| `profile.json` | the demo student's profile |
| `applications.json` | four applications, including a ghosted and a rejected one |
| `status.json` | the building → ready sequence for `/feed/status` |
| `transitions.json` | a copy of the backend's timeline graph, used **only** by the mock to compute `next_transitions`. Nothing in `src/app` or `src/components` reads it. If the backend's graph changes, the app needs no change; update this file so the mock keeps matching. |
| `index.ts` | the mock endpoints: same filters, both sort orders and pagination as the API, 300 ms latency |

Switches for tests, set in `localStorage`:

| Key | Effect |
|---|---|
| `step1.mock.instant = "1"` | `/feed/status` is `ready` on the first poll |
| `step1.mock.stuck = "1"` | `/feed/status` never leaves `building` |
| `step1.mock.ingest = "stale"` | which `ingest.json` scenario `/ingest/status` returns; `"error"` makes the route 404, like a backend that predates it |
| `step1.mock.fail = "POST /saved"` | the next matching request fails once with a 500 |

The mock also appends every request to `window.__step1Requests`
(`"GET /feed?page=1&…"`), which the specs use to check what the client sent.

## Data sources

Listings come from the
[SimplifyJobs](https://github.com/SimplifyJobs/Summer2027-Internships) and
[vanshb03](https://github.com/vanshb03/Summer2027-Internships) internship
lists. StEP1 links out to the original posting and credits both lists in the
page footer; it does not present the listings as its own.
