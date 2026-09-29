# StEP1 frontend

Internship discovery and application tracking. Next.js (App Router),
TypeScript and Tailwind, tested with Playwright.

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

Sign in with any email and a password of 8 or more characters.

- `demo@umd.edu` already has a profile and lands on the dashboard.
- Any other email is a new student and starts at onboarding.

Mock data lives in memory and is mirrored to `localStorage`, so a reload keeps
your saves and applications. Each mock user has their own. To reset, clear
site data (or remove the `step1.mock.v3` key).

### Against the real API

```bash
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
```

or copy `.env.example` to `.env.local` and edit it. The backend must allow
the frontend's origin in CORS (it defaults to `http://localhost:3000`) and
expose the `Retry-After` header.

| Variable | Meaning |
|---|---|
| `NEXT_PUBLIC_API_BASE` | `mock`, or the API's URL. Unset means `mock`, with a console warning. |
| `NEXT_PUBLIC_UPLOAD_ORIGIN` | Only when resumes upload straight to S3: the bucket's origin, so the Content-Security-Policy lets the browser PUT there. |

Both are read at build time.

## Test

```bash
npx playwright install chromium   # once
npm test                          # the suite, against the mock API
npm test -- --project=mobile      # the 375px project only
npm run test:prod                 # the production build, under the real security headers
npm run lint
npm run typecheck
npm run contrast                  # colour contrast of the palette
npm run headers:amplify -- --check
npm run build
npm audit --audit-level=high
```

What the suite covers:

| Spec | What it proves |
|---|---|
| `journey` | register, onboarding, building, dashboard, save, apply, advance the timeline |
| `dashboard` | filters and sort in the URL, empty states that name the filter, optimistic saves |
| `freshness` | the "listings updated" line in every state |
| `onboarding` | GPA is not collected, upload checks, input limits, rate limits |
| `account` | deleting the account |
| `public` | About and Privacy signed out, live numbers, footer links on every screen |
| `a11y` | axe on every screen and dialog, light and dark, desktop and 375px |
| `keyboard` | ranking interests, and save, apply, advance, with the keyboard alone |
| `mobile` | no horizontal scroll at 375px |
| `source` | no raw HTML, no inline styles, no mock imports in screens, palette contrast, headers in sync |
| `tests-prod/csp` | every screen works in the production build with no policy violation |

Ports and build directories are kept apart so nothing overwrites what you are
running on port 3000:

| Command | Port | Build directory |
|---|---|---|
| `npm run dev`, `npm start` | 3000 | `.next` |
| `npm test` | 3100 | `.next-test` |
| `npm run test:prod` | 3200 | `.next-prod` |

If you run `next start` on port 3000, remember that the API base is baked in
at build time: build with the base you intend to serve. For a throwaway
build that leaves `.next` alone, set `NEXT_DIST_DIR`:

```bash
NEXT_DIST_DIR=.next-check NEXT_PUBLIC_API_BASE=mock npm run build
```

Screenshots of every screen, light and dark, desktop and 375px:

```bash
SCREENSHOT_DIR=/tmp/step1-screens npm test -- screens
```

CI runs all of the above on every push and pull request that touches
`frontend/`: see `../.github/workflows/frontend-tests.yml`.

## Layout

```
src/
  app/                     one folder per route
    login/                 sign in / register
    onboarding/            profile, ranked interests, resume, delete account
    onboarding/building/   polls /feed/status until ready
    page.tsx               dashboard: feed, sort, filters, freshness line
    saved/
    applications/          list grouped by status
    applications/[id]/     timeline
    about/                 public
    privacy/               public
    icon.svg               favicon
    globals.css            the palette, fonts and corner sizes
  components/              cards, filter panel, ranker, timeline, dialogs, footer
  lib/
    api.ts                 the only module that talks to a backend
    auth.ts                token storage and useRequireAuth (swap for Cognito here)
    types.ts               the API contract, hand-written
    roles.ts               the 14 role keys and labels (mirrors backend roles.py)
    labels.ts              display labels for statuses, terms, degree levels
    limits.ts              the server's input bounds, mirrored
    site.ts                contact address, sources, and the hosting statement
    filters.ts             filters and sort <-> URL, empty-state diagnosis
    freshness.ts           wording rules for the "listings updated" line
    format.ts              dates, salary
    mock/                  in-browser API used when NEXT_PUBLIC_API_BASE=mock
scripts/
  contrast.mjs             checks the palette
  amplify-headers.mjs      writes the security headers into ../amplify.yml
security-headers.mjs       the headers, defined once
tests/                     Playwright specs (mock API, dev server)
tests-prod/                Playwright specs (production build)
```

### Rules the code follows

- **Every request goes through `src/lib/api.ts`.** Components never import
  mock data; `grep -ri mock src/components src/app` returns nothing.
- **The application state graph is not in the app.** The timeline renders its
  buttons from the `next_transitions` array the API returns. `labels.ts` maps
  identifiers to display text and nothing more.
- **Filters and sort are URL query params**, so a view can be linked and
  survives a reload.
- **Errors show the API's `detail` text.** A 429 is shown the same way, never
  signs the user out, and is never retried automatically.
- **No raw HTML.** `dangerouslySetInnerHTML` is a lint error, and a test
  covers `innerHTML`, `insertAdjacentHTML`, `document.write` and `eval`.
- **No inline styles.** The Content-Security-Policy forbids them.

## Look and feel

Brown, cream and white. The palette is a set of CSS variables in
`src/app/globals.css`; components use them through Tailwind classes such as
`bg-surface` and `text-muted`.

| Token | Light | Dark | Used for |
|---|---|---|---|
| `--bg` | `#f7f1e6` | `#17110d` | the page (cream) |
| `--surface` | `#ffffff` | `#211914` | cards, inputs, dialogs (white) |
| `--surface-2` | `#f1e8d9` | `#2c221b` | chips, tags, tinted rows |
| `--border` | `#e6dac6` | `#392c23` | decorative hairlines |
| `--border-strong` | `#917b5f` | `#846e59` | the edge of a control (3:1) |
| `--text` | `#2b1d13` | `#f3eadc` | body text |
| `--muted` | `#5e4b3c` | `#c2b2a0` | secondary text |
| `--faint` | `#756152` | `#a39281` | hints, placeholders, dates |
| `--accent` | `#6f4325` | `#d9a777` | score badges, primary buttons, focus ring (brown) |
| `--accent-soft` / `--accent-text` | `#f3e7d6` / `#6a3f22` | `#3a2a1d` / `#e3b98f` | reason chips, links |
| `--danger` | `#b3261e` | `#f2877b` | errors, rejected |
| `--positive` | `#2f6b3a` | `#8fcb8a` | offer, accepted |
| `--warn` | `#836400` | `#f0cc4d` | stale listings |

`--paper`, `--raise`, `--ink`, `--ink-2`, `--ink-3`, `--line` and `--line-2`
are aliases of the above, used by the About and Privacy pages. There is one
palette.

**Theme.** Dark mode follows the system. `<html data-theme="light">` or
`<html data-theme="dark">` overrides it. There is no toggle in the interface.

**Contrast.** `npm run contrast` reads the tokens from the stylesheet and
checks every text and background pair the components use: 4.5:1 for text,
including faint and placeholder text, and 3:1 for control boundaries, state
markers and focus rings, in both themes. It also checks that amber, red and
green stay clearly apart from the brown accent. If you change a colour, run
it.

**Type.** IBM Plex Sans for the interface (`font-ui`), Source Serif 4 for
prose on About and Privacy (`font-prose`), IBM Plex Mono for numbers
(`font-mono`). All three are self-hosted by `next/font`.

**Shape and motion.** Buttons and inputs have 4px corners (`rounded-control`),
cards 6px (`rounded-card`), chips 3px (`rounded-chip`). Nothing is
pill-shaped. No gradients, no emoji as icons (icons are inline SVG), no
scroll-triggered animation, no numbers that count up. The only motion is a
spinner, a progress bar and loading placeholders, and all of it stops under
`prefers-reduced-motion`.

**Copy.** Interface text, About and Privacy contain no em dashes.

## Accessibility

- axe runs on every screen and dialog, in both themes, at desktop width and
  at 375px. Any violation fails the build.
- Everything works from the keyboard. Focus is always visible (a 2px brown
  ring). Dialogs keep focus inside, start on their first field, close on
  Escape and hand focus back to what opened them.
- Ranking uses up and down buttons, so there is no drag-only control. Moves
  are announced to screen readers.
- Buttons that are briefly unusable (a save in flight, a move at the top of
  the list) stay focusable, so keyboard focus is never dropped.
- Icon-only buttons have names ("Save", "Remove Python", "Move Security up").
  Icons themselves are hidden from assistive technology. There are no images.
- After "I applied", focus moves to the new timeline link. After recording an
  event, it moves to "What happened next?" and the change is announced.

## The dashboard

**Order.** Newest first by default; "Best match" sorts by score. Score badges
and reason chips are on every card either way.

| Sort | URL | Sent to the API | Order |
|---|---|---|---|
| Newest first (default) | no `sort` param | `sort=recent` | date posted, newest first, undated last; then score; then id |
| Best match | `?sort=score` | `sort=score` | score, highest first; then date posted; then id |

The client sends `sort` on every `GET /feed`, including the one-row probes
behind the empty state. Changing the sort starts again at page 1. An
unrecognised `sort` in the URL is treated as the default.

**Freshness.** One line under the heading, from `GET /ingest/status`:

| Situation | Line | Look |
|---|---|---|
| Normal | Listings updated 3 hours ago · refreshes every 24 hours | quiet |
| `auto` is false | Listings updated 3 hours ago | quiet |
| `running` is true | Updating listings now… | checked again every 20 s |
| `last_success_at` is null | Listings haven't been loaded yet | quiet |
| Older than 2 × `interval_hours` | Listings last updated 3 days ago · a refresh is overdue | amber note |
| Every source has an `error` | Listings last updated 3 days ago · the last refresh failed | amber note |
| Some sources have an `error` | Listings last updated 3 hours ago · part of the last refresh failed | amber note |
| The endpoint fails or doesn't exist | nothing | the dashboard is unaffected |

## Profile, uploads and deleting an account

**What is collected.** School, major, minor, degree level, graduation year,
target terms, preferred locations, ranked interests and a resume. GPA is not
asked for and not sent: it never affected matching.

**Limits.** The form states the server's bounds before a request is made
(`src/lib/limits.ts`). If the server disagrees anyway, its message is shown.

| Field | Limit |
|---|---|
| School, major, minor | 120 characters |
| Display name | 80 characters |
| Preferred locations | 20 entries, 100 characters each |
| Note on an event | 2000 characters |
| Resume | PDF only, 1 KB to 5 MB |

**Upload.** The file is checked in the browser first. Then
`POST /profile/resume/presign` with `{filename, content_type, size}`, a PUT
of the bytes to the URL it returns, and `POST /profile/resume/commit`. The
headers the API returns are sent exactly as given. The bearer token is added
only when the upload URL is the API itself (local storage mode); a presigned
S3 URL is sent nothing extra.

**Delete my account.** At the bottom of Profile. The dialog lists what is
removed, asks for the password and needs a ticked box. It calls `DELETE /me`
with `{password}`. On success the token and local state are cleared and the
sign-in page confirms the deletion.

## Public pages

`/about` and `/privacy` need no sign-in and are linked from the footer of
every screen.

- **About.** The copy is the author's. The three numbers come from
  `GET /stats` and are printed flat. The row keeps its place while loading
  and is left out if the call fails.
- **Privacy.** States what the app does today. If the app starts or stops
  collecting something, change this page in the same commit.

`src/lib/site.ts` holds the contact address and a constant named `HOSTING`:
the sentences about where data lives. **Check them against the real
deployment before launch.**

## Security

### Headers

Every response carries these. They are defined once, in
`security-headers.mjs`, served by `next.config.ts`, and written into
`../amplify.yml` by `npm run headers:amplify`. A test fails if the two drift.

| Header | Value |
|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `X-Frame-Options` | `DENY` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` |
| `Content-Security-Policy` | below |

### Content-Security-Policy

In production:

```
default-src 'self';
script-src 'self' 'unsafe-inline';
style-src 'self';
img-src 'self' data:;
font-src 'self';
connect-src 'self' <API origin> <upload origin>;
object-src 'none';
frame-ancestors 'none';
base-uri 'self';
form-action 'self'
```

What had to be allowed, and why:

- **`'unsafe-inline'` for scripts.** Next writes the data each page needs to
  start into inline `<script>` tags. The pages are prerendered, so there is
  no request in which to mint a nonce, and the data differs per page and per
  build, so it can't be listed by hash in one header. Without this the pages
  load but never become interactive (checked: `script-src 'self'` alone
  blocks them). There is no `'unsafe-eval'` in production.
- **Nothing for styles.** All styling is in the site's stylesheet. The one
  inline style the app had (the progress bar's width) is now drawn as SVG.
- **`connect-src`** lists the API origin from `NEXT_PUBLIC_API_BASE` and, if
  set, `NEXT_PUBLIC_UPLOAD_ORIGIN`. Nothing else can be called, which also
  limits where a script could send anything.

Development adds `'unsafe-eval'` (React uses it for error stacks), inline
styles and the hot-reload websocket. Production never gets them.

The stricter option is a per-request nonce from `proxy.ts`. It removes
`'unsafe-inline'` but makes every page render on the server for every
request. It is a reasonable next step if the app ever renders user-written
markup.

**Before launch:** `amplify.yml` allows any App Runner or AWS host in
`connect-src`, because the real origins are not known yet. Pin them:

```bash
NEXT_PUBLIC_API_BASE=https://your-api-origin \
NEXT_PUBLIC_UPLOAD_ORIGIN=https://your-bucket.s3.amazonaws.com \
npm run headers:amplify
```

### Where the sign-in token is kept

In memory and in `localStorage`, by deliberate choice. It is sent as a bearer
token, so there is no cookie and no CSRF surface. The cost is that script on
the page could read it, which is why the app has no raw HTML, no third-party
scripts and the policy above. The reasoning is in `src/lib/auth.ts`.
`httpOnly` cookies would trade this for CSRF work and a harder Cognito swap.

### Dependencies

`npm audit --audit-level=high` runs in CI and fails the build on a high or
critical advisory.

## About `src/lib/mock/`

Test fixture data, not application logic. It exists so the interface can be
built and tested without the backend, and it answers with the same status
codes, headers and bodies as the real API.

| File | What it is |
|---|---|
| `feed.json` | 52 postings across all 14 roles, scores 22 to 95, two of them undated. `anchor` is the day the dates were written against; the mock shifts them so they stay relative to today |
| `profile.json` | the demo student's profile |
| `applications.json` | four applications, including a ghosted and a rejected one |
| `status.json` | the building to ready sequence for `/feed/status` |
| `ingest.json` | scenarios for `/ingest/status`, with times as hours-ago |
| `stats.json` | the numbers for `/stats` |
| `transitions.json` | a copy of the backend's timeline graph, used **only** by the mock to compute `next_transitions`. Nothing in `src/app` or `src/components` reads it |
| `index.ts` | the mock endpoints: same filters, sort orders and pagination as the API, 300 ms latency |

Switches for tests, set in `localStorage`:

| Key | Effect |
|---|---|
| `step1.mock.instant = "1"` | `/feed/status` is `ready` on the first poll |
| `step1.mock.stuck = "1"` | `/feed/status` never leaves `building` |
| `step1.mock.ingest = "stale"` | which `ingest.json` scenario `/ingest/status` returns; `"error"` makes the route 404 |
| `step1.mock.fail = "POST /saved"` | the next matching request fails once with a 500 |
| `step1.mock.fail = "429 POST /auth/login"` | the same, with a chosen status; 429 includes `Retry-After` |
| `step1.mock.fail = "always GET /stats"` | keeps failing until the key is removed |

Two file names change what the mock's upload returns: a name containing
`scan` comes back as an image-only PDF (`needs_ocr`), and one containing
`notpdf` is refused by commit with "That file isn't a PDF."

The mock appends every request to `window.__step1Requests` and its body to
`window.__step1Bodies` (passwords are never recorded), which the specs use
to check what the client sent.

## Troubleshooting

- **Type check fails on a file like `routes.d 2.ts`, or a build fails with
  "next/font/google queries have exactly one entry".** Both come from a
  damaged build directory, which a file-sync tool (iCloud Drive on a
  `Documents` folder, for one) can cause by copying or restoring files in
  it. Delete the build directory (`.next-test`, `.next-prod`, or `.next`
  with the dev server stopped) and run again. `npm run test:prod` always
  starts from a clean one and retries the build once.
- **The dev server restarts when you edit `next.config.ts`.** That is Next
  reloading its configuration.

## Data sources

Listings come from the
[SimplifyJobs](https://github.com/SimplifyJobs/Summer2027-Internships) and
[vanshb03](https://github.com/vanshb03/Summer2027-Internships) internship
lists. StEP1 links out to the original posting and credits both lists in the
page footer; it does not present the listings as its own.
