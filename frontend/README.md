# StEP1 frontend

Internship discovery and application tracking. Next.js (App Router),
TypeScript and Tailwind, tested with Playwright.

Design and API contract: [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)
(§5 API, §6 timeline).

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
site data (or remove the `step1.mock.v4` key).

### Against the real API

```bash
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
```

or copy `.env.example` to `.env.local` and edit it. The backend must allow
the frontend's origin in CORS (it defaults to `http://localhost:3000`) and
expose the `Retry-After` header.

### Settings

All of them are read when the site is built and baked into the files.
None is a secret: every `NEXT_PUBLIC_` value ends up in the browser.

| Variable | Meaning |
|---|---|
| `NEXT_PUBLIC_API_BASE` | `mock`, or the API's origin with no path. Unset means `mock`, with a console warning. |
| `NEXT_PUBLIC_UPLOAD_ORIGIN` | Only when resumes upload straight to S3: the bucket's origin. |
| `NEXT_PUBLIC_AUTH_MODE` | `local` (email and password, the default) or `cognito`. |
| `NEXT_PUBLIC_REGISTRATION` | Local mode only. `open` (the default) or `closed`, which hides Register. |
| `NEXT_PUBLIC_COGNITO_DOMAIN` | Cognito mode. The **user pool's own domain**, not the site's: `https://<prefix>.auth.<region>.amazoncognito.com`, or a custom Cognito domain. Unrelated to step1careers.com. |
| `NEXT_PUBLIC_COGNITO_CLIENT_ID` | Cognito mode. The app client id. It is a public client, with no secret. |
| `NEXT_PUBLIC_COGNITO_REDIRECT_URI` | Cognito mode. `https://step1careers.com/auth/callback`, exactly as registered, no trailing slash. |
| `NEXT_PUBLIC_COGNITO_LOGOUT_URI` | Cognito mode. Where Cognito returns after sign-out, for example `https://step1careers.com/login`. |

### The production build

```bash
npm run build     # a static export: plain files in out/
npm start         # serves out/ on port 3000, the way the host will
```

There is no Next server in production. `npm start` runs
`scripts/static-server.mjs`, which serves the files with the rewrite rule
and the security headers described under "Deploying to Amplify".

## Test

```bash
npx playwright install chromium   # once
npm test                          # the suite, against the dev server and the mock API
npm test -- --project=mobile      # the 375px project only
npm run test:prod                 # the exported site, served as files
npm run lint
npm run typecheck
npm run contrast                  # colour contrast of the palette
npm run headers:amplify -- --check
npm run build
npm audit --audit-level=high
```

What the suites cover:

| Spec | What it proves |
|---|---|
| `journey` | register, onboarding, building, dashboard, save, apply, advance the timeline |
| `dashboard` | filters and sort in the URL, empty states that name the filter, optimistic saves |
| `freshness` | the "listings updated" line in every state |
| `onboarding` | GPA is not collected, upload checks, input limits, rate limits |
| `account` | deleting the account |
| `applications` | grouping, ghosted styling, old-style links, the not-found page |
| `public` | About and Privacy signed out, live numbers, footer links on every screen |
| `reviews` | leaving a review, its checks and errors, the admin page, keyboard rating, axe at both widths |
| `admin-users` | the admin's Users tab: list, search, load more, a person's page, their resume download, 404 for others |
| `listings` | Looking for, the kind filter in the URL, the New grad tag, source labels, credit for every list |
| `resumes` | base resume, tailoring for a posting and for pasted text, saving, downloads, rename, delete, 409, 429, 503, keyboard, axe |
| `a11y` | axe on every screen and dialog, light and dark, desktop and 375px |
| `keyboard` | ranking interests, and save, apply, advance, with the keyboard alone |
| `mobile` | no horizontal scroll at 375px |
| `source` | no raw HTML, no inline styles, no mock imports in screens, palette contrast, headers in sync, no domain named |
| `tests-prod/static` | the exported site: every deep link, reloads, old links, the 404, fonts, favicon, headers, the policy, the whole journey |
| `tests-prod/cognito` | Cognito sign-in against a stand-in: the happy path, PKCE, state, every error, renewal, sign-out, deletion, axe |
| `tests-prod/registration` | `NEXT_PUBLIC_REGISTRATION` open and closed |

`npm run test:prod` builds the export three ways (local sign-in, local with
registration closed, Cognito) and serves each as plain files. Cognito is
played by `tests-prod/support/oidc-stub.mjs`, which has Cognito's endpoints,
checks the PKCE verifier, the redirect and the sign-out address, and signs
its tokens. No AWS account, no network.

Ports and directories are kept apart so nothing overwrites what you are
running on port 3000:

| Command | Ports | Writes to |
|---|---|---|
| `npm run dev` | 3000 | `.next/dev` |
| `npm run build` | none | `out/` (and `.next/`, Next's working directory) |
| `npm start` | 3000 | nothing |
| `npm test` | 3100 | `.next-test` |
| `npm run test:prod` | 3200, 3201, 3300, 3400 | `.next-export*` (and `.next/`) |

Two builds can't run at the same moment in one checkout: every export uses
`.next/` as its working directory, and Next locks it.

Screenshots of every screen, light and dark, desktop and 375px:

```bash
SCREENSHOT_DIR=/tmp/step1-screens npm test -- screens
```

CI runs all of the above on every push and pull request that touches
`frontend/`: see `../.github/workflows/frontend-tests.yml`.

## Layout

```
src/
  app/                     one folder per route; every route is a static file
    login/                 sign in (and register, in local mode)
    auth/callback/         where Cognito returns after sign-in
    onboarding/            profile, ranked interests, resume, delete account
    onboarding/building/   polls /feed/status until ready
    page.tsx               dashboard: feed, sort, filters, freshness line
    saved/
    applications/          list grouped by status
    application/           timeline, at /application?id=12
    review/                leave a review
    admin/                 the owner's page: reviews and users (?tab=users)
    admin/user/            one person, at /admin/user?id=12
    resume/                the base resume
    tailor/                tailoring, for a posting or pasted text
    resumes/               saved resumes; resumes/edit/ opens one
    about/                 public
    privacy/               public
    not-found.tsx          the 404 page; also forwards old-style links
    icon.svg               favicon
    globals.css            the palette, fonts and corner sizes
  components/              cards, filter panel, ranker, timeline, dialogs, footer
  lib/
    api.ts                 the only module that talks to a backend
    auth.ts                the session: what is stored, renewing, signing out
    cognito.ts             sign-in with Cognito: PKCE, the callback, refresh
    config.ts              build-time settings, and which token goes to the API
    routes.ts              addresses inside the site, and old ones that moved
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
  static-server.mjs        serves the export the way Amplify is documented to
  build-export.mjs         builds the export into a directory of its own
  check-deploy-env.mjs     refuses to build a deployment with bad settings
  amplify-headers.mjs      writes the security headers into ../amplify.yml
  contrast.mjs             checks the palette
security-headers.mjs       the headers and the policy, defined once
amplify-rewrites.json      the rewrite rule, exactly as entered in Amplify
tests/                     Playwright specs (dev server, mock API)
tests-prod/                Playwright specs (the exported site)
```

### Rules the code follows

- **Every request goes through `src/lib/api.ts`.** Components never import
  mock data; `grep -ri mock src/components src/app` returns nothing.
- **The application state graph is not in the app.** The timeline renders its
  buttons from the `next_transitions` array the API returns. `labels.ts` maps
  identifiers to display text and nothing more.
- **Filters and sort are URL query params**, so a view can be linked and
  survives a reload.
- **Every address is a file.** A timeline is `/application?id=12`, not
  `/applications/12`, so that a host that only serves files can answer it.
- **Nothing names a domain.** Addresses come from the settings above.
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

## Reviews and the admin page

Anyone signed in can leave a review at `/review`: a rating from 1 to 5 and
up to 2000 characters. The page says that it goes to Aggrey by email with
the writer's address attached. It is linked from the footer of every
signed-in screen and from the Profile page (not from the phone tab bar).
Calls: `POST /reviews`; the API's 422 and 429 messages are shown as they are.

`/admin` lists every review, newest first, with the count and the average
rating. It is for the owner only: `GET /me` says `is_admin`, and anyone
else, or anyone the API answers 404, sees the not-found page. The Admin link
appears in the desktop nav and on the Profile page only for the owner.
Calls: `GET /admin/reviews?page=&page_size=`. Review text is shown as plain
text with its line breaks, never as HTML.

In mock mode `demo@umd.edu` is the admin and `src/lib/mock/reviews.json`
holds twelve reviews; new ones are kept in the browser.

### Users

`/admin?tab=users` lists everyone, with search (`?q=`, by name, email, school
or major) and load more. `/admin/user?id=` shows one person: account,
profile, their uploaded resume (downloaded through a short-lived link the
API hands out), applications with their timelines, saved postings, tailored
resumes and reviews, under a banner that says this is another person's
data. Everything they wrote is plain text. Both are for the admin only;
anyone else gets the not-found page, as for reviews.
Calls: `GET /admin/users`, `GET /admin/users/{id}`,
`GET /admin/users/{id}/resume-file`.

## Internships and new grad roles

A profile says what the person is looking for: internships, new grad roles
or both (internships by default, at least one). The feed only shows those
kinds. The dashboard's Kind of role filter narrows it further and is kept in
the URL as `kind=internship` or `kind=new_grad`, like the other filters; the
empty state can name and drop it. New grad cards carry a small New grad tag,
and every card says which list it came from ("via SimplifyJobs"). A list the
app doesn't know yet shows under its own name.

The lists are credited by name with a link in the footer, on About and on
Privacy. They are defined once, in `SOURCES` in `src/lib/site.ts`; keep that
in step with the sources the API reads.

## Tailored resumes

- `/resume`: the **base resume**, which every tailored resume is built from.
  With none yet, the page offers to draft one from the uploaded resume
  (`POST /resume/base/extract`), or points to Profile to upload one first.
  It also keeps a list of every skill. `GET` and `PUT /resume/base`.
- `/tailor`: tailors for a posting (`/tailor?posting=<id>`, reached from the
  Tailor resume button on posting cards and on the timeline) or for pasted
  job text (up to 20,000 characters). `POST /tailor` takes 10 to 40 seconds;
  the page says it can take up to a minute and shows the seconds so far,
  never a made-up percentage. Then it shows the fit, what changed, the gaps
  and any question, above the editable draft, a name and Save.
- `/resumes`: saved resumes. Open (`/resumes/edit?id=`), rename in place,
  download, delete with a confirm.
- The **editor** is shared by the base and tailored resumes: name, contact
  lines, sections, entries and bullets, each added, removed and moved with
  buttons (never drag only), with quiet hints when a line runs long.
- **Downloads** (`GET /resumes/{id}/download?format=pdf|docx`) are fetched
  with the sign-in token, turned into a file in the browser and saved under
  the name in the response's `Content-Disposition`. Across origins a browser
  can only read that header if the API lists it in
  `Access-Control-Expose-Headers`; otherwise a fallback name is used.
  Downloading an unsaved resume saves it first.

What tailoring sends to Amazon Bedrock, and what is kept, is on the Privacy
page.

## Security

### Headers

The site is plain files, so the host sets the headers. They are defined
once, in `security-headers.mjs`. `npm run headers:amplify` writes them into
`../amplify.yml`, a test fails if the two drift, and `next dev` and the test
server send the same set.

| Header | Value |
|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `X-Frame-Options` | `DENY` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` |
| `Content-Security-Policy` | below |

### Content-Security-Policy

The policy is delivered twice, and a browser enforces both.

**As a header, from the host.** It is the same for every environment,
because it names no domain:

```
default-src 'self';
script-src 'self' 'unsafe-inline';
style-src 'self';
img-src 'self' data:;
font-src 'self';
connect-src 'self' https:;
object-src 'none';
frame-ancestors 'none';
base-uri 'self';
form-action 'self'
```

**As a `<meta>` tag in every page, written at build time.** It is the same
policy without `frame-ancestors` (a tag can't carry it), and with
`connect-src` narrowed to the exact origins the build was configured with:

```
connect-src 'self' <API origin> <upload origin> <Cognito domain, in cognito mode only>
```

A request has to pass both, so the effective rule is the exact list.
Change a setting, rebuild, and the policy follows: there is nothing to edit
by hand.

What had to be allowed, and why:

- **`'unsafe-inline'` for scripts.** Next writes the data each page needs to
  start into inline `<script>` tags. The pages are static files, so there is
  no request in which to mint a nonce, and the data differs per page and per
  build, so it can't be listed by hash in one header. Without this the pages
  load but never become interactive. There is no `'unsafe-eval'` in
  production.
- **Nothing for styles.** All styling is in the site's stylesheet.
- **Nothing for the Cognito redirect.** Going to Cognito and coming back are
  navigations, which a Content-Security-Policy does not govern. Only the
  token exchange is a request made by the page, hence the Cognito domain in
  `connect-src`.

Development adds `'unsafe-eval'` (React uses it for error stacks), inline
styles and the hot-reload websocket. Production never gets them.

### Where the sign-in token is kept

In memory and in `localStorage`, by deliberate choice. It is sent as a bearer
token, so there is no cookie and no CSRF surface. The cost is that script on
the page could read it, which is why the app has no raw HTML, no third-party
scripts and the policy above. In cognito mode the refresh token is kept the
same way. `httpOnly` cookies would need a server in front of the API to hold
them, and the site is static files. The reasoning is in `src/lib/auth.ts`.

### Dependencies

`npm audit --audit-level=high` runs in CI and fails the build on a high or
critical advisory.

## Signing in

Chosen when the site is built, with `NEXT_PUBLIC_AUTH_MODE`.

### local (the default)

Email and password, checked by the StEP1 API. With
`NEXT_PUBLIC_REGISTRATION=closed` the sign-in page has no Register tab; the
API's own registration is expected to be off as well.

### cognito

Amazon Cognito's managed login, for a user pool with self-sign-up turned
off. StEP1 never sees a password.

1. "Sign in" makes a code verifier, a state and a nonce, keeps them in the
   tab's `sessionStorage`, and sends the browser to
   `<cognito domain>/oauth2/authorize` (the user pool's own domain, from
   `NEXT_PUBLIC_COGNITO_DOMAIN`, not step1careers.com) with
   `response_type=code`, `code_challenge_method=S256`, the challenge, the
   state, the nonce and `scope=openid email profile`. There is no client
   secret.
2. Cognito signs the person in and returns to
   `https://step1careers.com/auth/callback?code=...&state=...`.
3. The callback page checks the state, exchanges the code and the verifier
   at `<cognito domain>/oauth2/token`, checks the ID token's nonce, audience
   and expiry, stores the session, and goes on to where the person was
   heading.

**Which token goes to the API: the ID token.** Its `aud` is the app client
id and its `token_use` is `id`, and it carries `email` and `name`, which the
API uses to create the user's row. The access token carries neither. It is
not sent anywhere and not kept. The one place this is decided is
`src/lib/config.ts`.

**Staying signed in.** A token with under a minute left is renewed with the
refresh token before it is used. A token the API refuses (401) is renewed
and the request repeated once. If it can't be renewed, the page the person
was on is remembered, they sign in again, and they come back to it.

**Signing out** clears the session here and goes through
`<cognito domain>/logout?client_id=...&logout_uri=...`, which ends Cognito's
own session.

**Delete my account** asks for the word DELETE instead of a password, and
leaves through Cognito's sign-out.

What the person is told when it goes wrong:

| What happened | What they read |
|---|---|
| They cancelled | Sign-in was cancelled. You left sign-in before it finished. Nothing was changed. |
| The reply doesn't match a sign-in this tab started | Sign-in was stopped. This sign-in was not started from this browser tab, so it was stopped to keep your account safe. Start again from here. |
| The code expired or was used already | That sign-in ran out of time. It took too long, or the link was already used. Start again and it will work. |
| The account isn't invited | That account has not been invited. StEP1 is invite only for now, and this account is not on the list. |

## Deploying to Amplify

The site is `step1careers.com`, its API is `api.step1careers.com`, and it is
hosted as **static files**. AWS Amplify Hosting runs Next.js server
rendering only up to Next.js 15, and this is Next.js 16; nothing here needs
a server, because every page is rendered in the browser against the API.

Nothing below has been done. These are the steps, in order, with where each
fact comes from. "Docs" means the AWS Amplify Hosting user guide or the
Amazon Cognito developer guide, read in September 2026.

### 1. Create the app as a static site

- Connect the repository, tick **My app is a monorepo**, and enter
  `frontend` as the app root. Amplify then sets
  `AMPLIFY_MONOREPO_APP_ROOT=frontend`, which must match `appRoot` in
  `amplify.yml`. (Docs: "Configuring monorepo build settings".)
- The app's **platform must be `WEB`**, which is Amplify's name for a static
  site. If Amplify detects Next.js and creates it as `WEB_COMPUTE`, change
  it. The docs give the command for the opposite direction,
  `aws amplify update-app --app-id <id> --platform WEB_COMPUTE`; use `WEB`.
  (Docs: "Adding SSR functionality to a static Next.js app".)
- Build settings come from `../amplify.yml`, which overrides anything
  entered in the console: Node 22, `npm ci`, the settings check,
  `npm run build`, and `out` as the artifact directory.

### 2. Set the environment variables

In the Amplify console, under Hosting, Environment variables. They are read
by the build. `npm run check:deploy` runs first and stops the build if they
are wrong, including the case that matters most: with no API address the
site would quietly run on made-up data.

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_BASE` | `https://api.step1careers.com` |
| `NEXT_PUBLIC_AUTH_MODE` | `cognito` |
| `NEXT_PUBLIC_COGNITO_DOMAIN` | the user pool's **own** domain, e.g. `https://step1careers.auth.us-east-1.amazoncognito.com`: a Cognito prefix or custom domain, not `step1careers.com` itself |
| `NEXT_PUBLIC_COGNITO_CLIENT_ID` | the app client id |
| `NEXT_PUBLIC_COGNITO_REDIRECT_URI` | `https://step1careers.com/auth/callback` |
| `NEXT_PUBLIC_COGNITO_LOGOUT_URI` | `https://step1careers.com/login` |
| `NEXT_PUBLIC_UPLOAD_ORIGIN` | the resume bucket's origin, if uploads go straight to S3 |

In Cognito, the app client needs the redirect URI among its allowed callback
URLs and the logout URI among its allowed sign-out URLs, both exactly as
written here, the authorization code grant enabled, the scopes `openid`,
`email` and `profile`, and **no client secret**.

### 3. Enter the rewrite rule

Rewrites are kept in the app's settings, not in `amplify.yml`. In the
Amplify console: **Hosting**, **Rewrites and redirects**, **Manage
redirects**, then replace what is in the JSON editor with the contents of
`amplify-rewrites.json` and choose **Save**. (Docs: "Creating and editing
redirects in the Amplify console".)

```json
[
  {
    "source": "/<*>",
    "target": "/404.html",
    "status": "404",
    "condition": null
  }
]
```

That is the whole list. It serves the site's own 404 page, with a 404
status, for any address that has no file. Rules are applied from the top
down, so nothing may come before it that catches every address: if Amplify
has put a rule of its own there (its documentation refers to a "default 404
rewrite rule"), or a single-page-app rule that sends everything to
`/index.html`, remove it. With such a rule every mistyped address would
show the dashboard, and old links would stop working.

No rule is needed for the pages themselves. Amplify serves `/about` from
`about.html` without being told. (Docs: "Redirects and rewrites example
reference", under "Trailing slashes and clean URLs".)

Old links in the form `/applications/12` need no rule either. They have no
file, so they get the 404 page, and that page sends them to
`/application?id=12`.

### 4. The headers

They are in `amplify.yml` under `customHeaders`, generated from
`security-headers.mjs`. After changing that file:

```bash
npm run headers:amplify
```

They name no domain, so there is nothing to fill in at launch.

AWS now recommends keeping custom headers in a `customHttp.yml` file at the
root of the repository rather than in `amplify.yml`. Both are read. To move
them, save the output of `npm run headers:amplify -- --print` as
`customHttp.yml` in the repository root and delete the block from
`amplify.yml`. (Docs: "Setting custom headers for an Amplify app",
"Monorepo custom header requirements".)

### 5. Check the live site

Before the domain is attached, use the address Amplify gives you
(`https://<branch>.<app-id>.amplifyapp.com`) in place of
`https://step1careers.com` below; afterwards, use the real domain.

```bash
site=https://step1careers.com

# every page is a file, and answers 200
for p in / /login /auth/callback /onboarding /onboarding/building /saved \
         /applications "/application?id=1" /about /privacy; do
  curl -s -o /dev/null -w "%{http_code}  $p\n" "$site$p"
done

# an unknown address answers 404 with the site's own page
curl -s -o /dev/null -w "%{http_code}\n" "$site/no/such/page"      # 404
curl -s "$site/no/such/page" | grep -c "Page not found"            # 1

# the headers
curl -sI "$site/" | grep -iE "strict-transport|x-frame|x-content|referrer|permissions|content-security"

# the policy in the page names the real API and Cognito origins
curl -s "$site/login" | grep -o 'connect-src[^;]*'

# nothing is fetched from anywhere but the site
curl -s "$site/login" | grep -oE 'https?://[^"]+' | sort -u
```

Then, in a browser, with the developer tools console open:

1. `/about` shows three numbers. If the row is missing, the API is not
   reachable or its CORS settings don't include the site.
2. Sign in. You should leave for Cognito and come back signed in.
3. Reload on `/saved`, on a filtered dashboard, and on a timeline. Each
   should come back as it was.
4. Open `/applications/1`. The address should become `/application?id=1`.
5. The console should show no Content-Security-Policy messages.

### What can only be checked on the real thing

The test server is a model built from the documentation. These are the
places where Amplify or Cognito could differ from it:

- That Amplify serves `/about` from `about.html` when a folder named
  `about/` also exists in the export (it holds Next's navigation data).
- That the `customHeaders` pattern `'**'` covers every path, including `/`.
- That a new Amplify app for this repository comes up as `WEB`.
- What Cognito sends back when someone cancels or isn't allowed in. The app
  recognises `access_denied` and descriptions that mention sign-up not being
  permitted; anything else gets the general message.
- That the API accepts the ID token.

## About `src/lib/mock/`

Test fixture data, not application logic. It exists so the interface can be
built and tested without the backend, and it answers with the same status
codes, headers and bodies as the real API.

| File | What it is |
|---|---|
| `feed.json` | 52 internships across all 14 roles, scores 22 to 95, two of them undated, plus 6 new grad roles; a few come from the newer lists and one from a list the app doesn't know. `anchor` is the day the dates were written against; the mock shifts them so they stay relative to today |
| `base-resume.json` | a fictional student's base resume (example.edu address, 555 phone number) |
| `tailor.json` | the canned tailoring answers, for a posting and for pasted text; tailoring takes two seconds |
| `admin-users.json` | twenty-four fictional people for the admin's Users tab |
| `reviews.json` | twelve reviews for the admin page |
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
| `step1.mock.fail = "429 POST /tailor"` | 429, 409 and 503 on `/tailor`, `/reviews` and `/resume/base/extract` use those routes' own messages |

Two file names change what the mock's upload returns: a name containing
`scan` comes back as an image-only PDF (`needs_ocr`), and one containing
`notpdf` is refused by commit with "That file isn't a PDF."

The mock appends every request to `window.__step1Requests` and its body to
`window.__step1Bodies` (passwords are never recorded), which the specs use
to check what the client sent.

## Troubleshooting

- **A build fails with "next/font/google queries have exactly one entry",
  or type checking fails on a file like `routes.d 2.ts`.** The build
  directory is damaged. A file-sync tool (iCloud Drive on a `Documents`
  folder, for one) can do that by copying or restoring files in it. Delete
  `.next`, `.next-test` and `.next-export*` and run again, and keep the
  checkout out of synced folders.
- **"Another next build process is already running".** Two builds at once in
  one checkout. Wait for the first.
- **The deployed site shows made-up data.** It was built without
  `NEXT_PUBLIC_API_BASE`. `npm run check:deploy` exists to stop that; make
  sure the build runs it.
- **Sign-in returns to "Sign-in was stopped" every time.** The redirect URI
  in the settings and the one registered in Cognito differ, often by a
  trailing slash, or the site is being opened on a different address from
  the one in the redirect URI (the two keep separate browser storage).

## Data sources

Listings come from community-maintained lists on GitHub, all credited by name
with a link in the page footer: SimplifyJobs (internships and new grad
positions), vanshb03, Jobright (data analysis, business analyst and product
management internships), SpeedyApply (AI college jobs) and Zapply
(internships). See `SOURCES` in `src/lib/site.ts`. StEP1 links out to the
original posting and does not present the listings as its own.
