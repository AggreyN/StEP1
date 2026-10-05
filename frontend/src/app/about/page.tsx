/**
 * StEP1: About / origin story.  Route: /about  (public, no sign-in)
 *
 * Laid out like the "Ledger" design (docs/DESIGN_LEDGER.md §4): a top bar,
 * a wide hero with the stats beside the headline, the story in two columns,
 * what it does as three numbered columns, then one tan band holding the
 * roadmap and the contact block.
 *
 * Design notes, so nobody "improves" this into the thing it avoids:
 *  - No gradient hero, no stock or generated imagery, no scroll animation.
 *  - Buttons are 4px radius, not pills. Icons would be SVG, never emoji.
 *  - The stats are real numbers from the API (GET /stats). Render them flat.
 *    Do NOT animate them counting up, which is the tell this page exists to
 *    avoid.
 *  - The copy contains no em dashes. That was deliberate; keep it that way
 *    if you edit.
 *  - One filled block on the page (the band with contact), so it reads as
 *    the single action.
 *  - Prose is serif, section labels are sans, same as Privacy.
 *
 * Colours are the app's tokens under the names this page was written with
 * (--paper, --ink, --line ...); see globals.css.
 */
import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { AboutStats } from "@/components/AboutStats";
import { CopyEmail } from "@/components/CopyEmail";
import { SectionLabel } from "@/components/prose";
import { SiteFooter } from "@/components/SiteFooter";
import { CONTACT_MAILTO, SOURCES } from "@/lib/site";

export const metadata: Metadata = {
  title: "About",
  description:
    "Why StEP1 exists: it finds internships worth applying to and remembers what happened after you applied.",
};

const ROADMAP = [
  {
    when: "Next",
    what: "Gmail connection, so a confirmation or interview email advances your timeline without you touching it.",
  },
  {
    when: "Next",
    what: "GitHub sign-in, reading your repo languages to seed your skills instead of making you type them.",
  },
  {
    when: "Soon",
    what: "Recruiter outreach drafts and follow-up reminders, on a schedule that knows when you last heard anything.",
  },
  {
    when: "Later",
    what: "Roles outside tech. The boards I pull from are engineering-heavy, and my friends outside CS deserve the same tool.",
  },
];

/** A ruled section with its sans label. */
function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="mt-16 border-t border-[var(--line)] pt-8">
      <SectionLabel>{label}</SectionLabel>
      {children}
    </section>
  );
}

/** One of the three numbered columns under "What it does today". */
function Feature({ n, title, children }: { n: string; title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2.5">
      <span className="font-mono text-[0.85rem] text-[var(--accent-text)]">{n}</span>
      <h3 className="font-ui m-0 text-[1.15rem] font-semibold">{title}</h3>
      <p className="m-0 text-[0.98rem] text-[var(--ink-2)]">{children}</p>
    </div>
  );
}

export default function AboutPage() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-[var(--line)] bg-[var(--surface-2)]">
        <div className="font-ui mx-auto flex max-w-[1152px] items-center gap-2 px-5 py-3 sm:gap-4 sm:px-8">
          <Link
            href="/"
            className="font-prose text-[1.6rem] font-semibold tracking-[-0.01em] text-[var(--ink)] no-underline"
          >
            StEP<span className="text-[var(--accent-text)]">1</span>
          </Link>
          <nav aria-label="Primary" className="ml-auto flex items-center gap-1 text-[0.9rem]">
            <Link
              href="/"
              className="rounded-[4px] px-3 py-2.5 text-[var(--ink-2)] no-underline hover:text-[var(--ink)]"
            >
              Matches
            </Link>
            <span
              aria-current="page"
              className="rounded-[4px] bg-[var(--accent-soft)] px-3 py-2.5 font-semibold text-[var(--ink)]"
            >
              About
            </span>
          </nav>
          <Link
            href="/login"
            className="hidden min-h-11 items-center rounded-[4px] bg-[var(--accent)] px-4 text-[0.9rem] font-semibold text-[var(--accent-fg)] no-underline hover:bg-[var(--accent-hover)] sm:inline-flex"
          >
            Get started
          </Link>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1152px] px-5 pb-20 pt-12 font-prose leading-[1.65] text-[var(--ink)] sm:px-8 sm:pt-20">
        <section className="grid gap-10 lg:grid-cols-12 lg:gap-6">
          <div className="lg:col-span-8">
            <div className="font-ui mb-5 text-[0.76rem] font-semibold uppercase tracking-[0.12em] text-[var(--ink-3)]">
              About StEP1
            </div>
            <h1 className="mb-6 text-[clamp(2.25rem,6vw,4rem)] font-semibold leading-[1.06] tracking-[-0.025em] [text-wrap:balance]">
              I kept losing track of my own applications.
            </h1>
            <p className="m-0 max-w-[56ch] text-[1.15rem] text-[var(--ink-2)] sm:text-[1.2rem]">
              So I built the thing I wanted to exist. StEP1 finds internships worth
              applying to and remembers what happened after you applied.
            </p>
          </div>
          <div className="lg:col-span-4 lg:self-end">
            <AboutStats layout="stack" />
          </div>
        </section>

        <Section label="Why I built it">
          <div className="grid gap-x-12 gap-y-[18px] sm:grid-cols-2 [&>p]:m-0">
            <p>
              I&apos;m Aggrey Narh. I&apos;m a junior at the University of Maryland,
              College Park, studying Information Science with a minor in Data
              Science.
            </p>
            <p>
              Last recruiting season I did what most students do. A spreadsheet.
              Twelve browser tabs. A GitHub list I checked twice a week and forgot
              about in between. By February I couldn&apos;t tell you which companies
              had rejected me, which had gone quiet, and which I had opened and never
              finished applying to.
            </p>
            <p>
              I like two things: writing code, and getting paid for it. StEP1 is what
              happened when I pointed the first at the second.
            </p>
            <p>
              The first version was a script that pulled a JSON file and printed
              matches to my terminal. It was useful enough that my friends started
              asking me to run it for them. That&apos;s the part that turned it from a
              weekend into a project.
            </p>
          </div>
        </Section>

        <Section label="What it does today">
          <div className="grid gap-8 md:grid-cols-3 md:gap-6">
            <Feature n="01" title="Finds">
              StEP1 pulls from community-maintained internship and new grad boards,
              then classifies every posting by role and scores it against your
              profile.
            </Feature>
            <Feature n="02" title="Explains">
              The scoring is a weighted sum, not a black box. Every match tells you
              why it matched: which of your ranked fields it hit, which of your
              skills appear in the posting, how recently it went up. If a score looks
              wrong, you can see exactly which rule made it wrong.
            </Feature>
            <Feature n="03" title="Tracks">
              The part I use most is the tracker. Applied, heard back, online
              assessment, interview, another round, offer. Every change is a
              timestamped event, so the history stays instead of being overwritten by
              a status column. There&apos;s a state for{" "}
              <strong className="font-semibold text-[var(--ink)]">ghosted</strong> too,
              because that is where most applications quietly end up and no tracker
              I&apos;ve used will say so out loud.
            </Feature>
          </div>

          <p
            className="font-ui mb-0 mt-8 max-w-[90ch] text-[0.85rem] text-[var(--ink-2)]"
            data-testid="about-sources"
          >
            The boards:{" "}
            {SOURCES.map((src, i) => (
              <span key={src.url}>
                <a
                  href={src.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-[var(--accent-text)] underline underline-offset-2"
                >
                  {src.name}
                </a>
                {i < SOURCES.length - 2 ? ", " : i === SOURCES.length - 2 ? " and " : "."}
              </span>
            ))}
          </p>
        </Section>

        <section className="mt-16 grid gap-10 rounded-[6px] bg-[var(--surface-2)] p-6 sm:p-10 lg:grid-cols-2 lg:gap-12">
          <div>
            <SectionLabel>Where it&apos;s going</SectionLabel>
            <p className="mb-3 mt-0 max-w-[62ch] text-[var(--ink-2)]">
              It&apos;s early. Here&apos;s what&apos;s actually next, in the order I
              plan to build it.
            </p>
            <ul className="m-0 flex list-none flex-col p-0">
              {ROADMAP.map((r, i) => (
                <li
                  key={r.what}
                  className={`flex items-baseline gap-[14px] py-[12px] ${
                    i < ROADMAP.length - 1 ? "border-b border-[var(--line)]" : ""
                  }`}
                >
                  <span className="font-ui min-w-[56px] flex-none rounded-[3px] bg-[var(--paper)] px-[7px] py-[3px] text-center text-[0.66rem] font-semibold uppercase tracking-[0.07em] text-[var(--accent-text)]">
                    {r.when}
                  </span>
                  <span className="min-w-0">{r.what}</span>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <SectionLabel>Contact me</SectionLabel>
            <p className="mb-0 mt-0 max-w-[62ch] text-[var(--ink-2)]">
              Found a bug, want an invite, or think this should do something it
              doesn&apos;t? Send me a note. I read all of them.
            </p>
            <div className="mt-5 flex flex-wrap items-center gap-[10px]">
              <CopyEmail />
            </div>
            <div className="mt-[18px]">
              {/* Opens the visitor's default mail client with To: already filled. */}
              <a
                href={CONTACT_MAILTO}
                className="font-ui inline-flex min-h-11 items-center rounded-[4px] bg-[var(--accent)] px-5 text-[0.9rem] font-semibold text-[var(--accent-fg)] no-underline hover:bg-[var(--accent-hover)]"
              >
                Contact me
              </a>
            </div>
          </div>
        </section>

        <p className="font-ui mb-0 mt-12 border-t border-[var(--line)] pt-5 text-[0.8rem] text-[var(--ink-3)]">
          Built by Aggrey Narh at the University of Maryland. StEP1 stores resumes
          and application history, so there&apos;s a{" "}
          <Link href="/privacy" className="text-[var(--ink-2)] underline underline-offset-2">
            privacy policy
          </Link>{" "}
          worth two minutes of your time.
        </p>
      </main>
      <SiteFooter />
    </div>
  );
}
