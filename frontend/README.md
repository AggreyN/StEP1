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

Screenshots of every screen, light and dark, desktop and 375px:

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
    page.tsx               dashboard: scored feed + filters
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
    filters.ts             filters <-> URL, empty-state diagnosis
    format.ts              dates, salary
    mock/                  in-browser API used when NEXT_PUBLIC_API_BASE=mock
tests/                     Playwright specs
```

### Rules the code follows

- **Every request goes through `src/lib/api.ts`.** Components never import
  mock data; `grep -ri mock src/components` returns nothing.
- **The application state graph is not in the app.** The timeline renders its
  buttons from the `next_transitions` array the API returns. `labels.ts` maps
  identifiers to display text and nothing more.
- **Filters are URL query params**, so a filtered view can be linked and
  survives a reload.
- **Errors show the API's `detail` text.**

### About `src/lib/mock/`

Test fixture data, not application logic. It exists so the UI can be built
and tested before (and without) the backend, and it answers with the same
status codes, headers and bodies as the real API.

| File | What it is |
|---|---|
| `feed.json` | 52 postings across all 14 roles, scores 22–95 |
| `profile.json` | the demo student's profile |
| `applications.json` | four applications, including a ghosted and a rejected one |
| `status.json` | the building → ready sequence for `/feed/status` |
| `transitions.json` | a copy of the backend's timeline graph, used **only** by the mock to compute `next_transitions`. Nothing in `src/app` or `src/components` reads it. If the backend's graph changes, the app needs no change; update this file so the mock keeps matching. |
| `index.ts` | the mock endpoints: same filters, sorting and pagination as the API, 300 ms latency |

Switches for tests, set in `localStorage`:

| Key | Effect |
|---|---|
| `step1.mock.instant = "1"` | `/feed/status` is `ready` on the first poll |
| `step1.mock.stuck = "1"` | `/feed/status` never leaves `building` |
| `step1.mock.fail = "POST /saved"` | the next matching request fails once with a 500 |

## Data sources

Listings come from the
[SimplifyJobs](https://github.com/SimplifyJobs/Summer2027-Internships) and
[vanshb03](https://github.com/vanshb03/Summer2027-Internships) internship
lists. StEP1 links out to the original posting and credits both lists in the
page footer; it does not present the listings as its own.
