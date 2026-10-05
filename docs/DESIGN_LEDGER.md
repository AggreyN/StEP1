# StEP1 visual design: "Ledger"

The chosen look for the frontend. Quiet, dense, warm paper and dark espresso
brown. Mockups: https://claude.ai/artifact/USMyWrPEZtqWEWSZ6q2qK4 (boards
"A · Ledger" and "A · About").

This file is the source of truth for colors, type and layout. `FRONTEND_BRIEF.md`
still owns behavior, routes and the API contract.

## 1 · Tokens (`src/app/globals.css`)

Every color in the app comes from these variables. No hex values in components.

```css
:root {
  --paper:       #f1e9dc; /* page background */
  --rail:        #e5d8c4; /* sidebar, top bar, tan feature band */
  --rail-active: #d6c4a8; /* active nav item */
  --raise:       #fffdf8; /* rows, cards, inputs */
  --ink:         #1f1d1a; /* primary text */
  --ink-2:       #4a453d; /* body copy, secondary */
  --ink-3:       #6b655b; /* labels, meta, captions */
  --line:        #dccdb6; /* dividers, row borders */
  --line-2:      #cdbb9f; /* input and button borders */
  --accent:      #4a2a17; /* espresso: score >= 80, primary buttons, rank numbers */
  --accent-hover:#2e190c;
  --accent-soft: #efe2d2; /* reason chips, roadmap tags */
  --on-accent:   #ffffff;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper:#17130f; --rail:#1f1914; --rail-active:#2e251d; --raise:#221b16;
    --ink:#efe7da; --ink-2:#c4b8a6; --ink-3:#968a79;
    --line:#33291f; --line-2:#4a3d30;
    --accent:#d9a57a; --accent-hover:#e8bd97; --accent-soft:#2e2219; --on-accent:#17130f;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] { /* same dark values as above */ }
```

Espresso is too dark to read on a dark background, so dark mode uses a light
caramel accent from the same family. Primary buttons then use `--on-accent`
text.

## 2 · Type (`src/app/layout.tsx`, `next/font/google`)

| Role | Font | Used for |
|---|---|---|
| Display / prose | **Newsreader** 400/500/600 | Logo, page titles (40px dashboard, 64px About hero), section headings, About paragraphs |
| UI | **Work Sans** 400/500/600 | Everything else: nav, labels, buttons, chips, table text |
| Numbers | **IBM Plex Mono** 500 | Scores, counts, stats, rank numbers, email address |

Expose them as `--font-display`, `--font-ui`, `--font-mono` and Tailwind
`font-display`, `font-ui`, `font-mono`. Small uppercase labels: 11-12px,
600, `tracking-[0.12em]`, `--ink-3`.

## 3 · Dashboard (`/`)

- Two columns: **248px left sidebar** (`--rail`, right border `--line`) +
  main area (`--paper`, 32px/40px padding).
- Sidebar top to bottom: logo "StEP**1**" (the 1 in `--accent`); nav
  (Matches, Saved, Applications, Profile, About) with counts right-aligned in
  mono, active item on `--rail-active`; "Your fields, ranked" list with mono
  rank numbers in `--accent`; filters (terms, location, remote, min-score
  slider).
- Main header: small date line ("Tuesday, Sept 29 · 14 new since
  yesterday") over a 40px Newsreader "Your matches"; search input on the right
  (44px tall, `--raise`, `--line-2` border, 8px radius).
- **Matches are table rows, not cards.** Grid columns
  `64px | 1fr | 180px | 120px`: score, title + reasons, location + term/age,
  actions. Column headers are uppercase labels. Each row: `--raise` background,
  bottom border `--line`, 16px padding.
  - Score: 22px mono. `--accent` when >= 80, `--ink-3` below.
  - Title 16px/600 then " · Company" in `--ink-3`/400.
  - Reasons: 12px chips, `--accent-soft` background, `--accent` text, 4px
    radius. This is the product's differentiator, so keep them visible.
  - Actions: 44x44 outline save button (stroke SVG icon, never emoji) and a
    filled `--accent` "Applied" button.
- Under 768px the sidebar becomes a top bar + filter sheet and rows stack.
  No horizontal scroll at 375px.

## 4 · About (`/about`)

The existing `about-page.tsx` copy stays word for word, with no em dashes. Two
changes to it: remove "Most people call me Ussop." and replace its green tokens
and fonts with the ones above. Layout, top to bottom, max width 1280 with
64px side padding:

1. **Top bar** (76px, `--rail`, bottom border): logo left; Matches / About
   nav (About active); "Get started" filled accent button → `/`.
2. **Hero**, 12-col grid: left 8 cols = uppercase "About StEP1" label, 64px
   Newsreader headline "I kept losing track of my own applications.", 19px
   intro in `--ink-2`. Right 4 cols = one `--raise` card, 12px radius,
   bottom-aligned, holding the three stats stacked (36px mono numbers in
   `--accent`, 13px labels), divided by `--line`. Render numbers flat, never
   counting up.
3. **Why I built it**: 34px Newsreader heading, top border, the four
   paragraphs in a 2-column grid (16px, line-height 1.65, `--ink-2`).
4. **What it does today**: same heading style, 3 columns, each with a mono
   "01/02/03" in `--accent`, a 20px/600 title (**Finds**, **Explains**,
   **Tracks**) and the matching existing paragraph.
5. **Tan band** (`--rail`, 12px radius, 40px padding, 2 columns): left
   "Where it's going" + the roadmap list (tags on `--paper`, `--accent` text);
   right "Contact me" with the email in a mono box, a Copy button (shows
   "Copied" for 1.8s, with an `aria-live` status) and a filled "Contact me"
   mailto link.
6. **Footer**: top border, the "Built by Aggrey Narh…" privacy line on the
   left, "See your matches →" on the right.

Single column below 768px: hero stats card moves under the headline, all
grids collapse to one column.

## 5 · Shared rules

- Buttons and inputs 44px tall minimum, 8px radius. One accent, used only for
  scores >= 80, primary actions, rank numbers and chips.
- No gradients, no shadows, no emoji, no count-up or scroll animations.
- Text contrast 4.5:1 minimum; every icon-only button has an `aria-label`.
