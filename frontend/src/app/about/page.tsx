/**
 * StEP1: About / origin story.  Route: /about  (public, no sign-in)
 *
 * Design notes, so nobody "improves" this into the thing it avoids:
 *  - No gradient hero, no stock or generated imagery, no scroll animation.
 *  - Buttons are 4px radius, not pills. Icons would be SVG, never emoji.
 *  - The stats are real numbers from the API (GET /stats). Render them flat.
 *    Do NOT animate them counting up, which is the tell this page exists to
 *    avoid.
 *  - The copy contains no em dashes. That was deliberate; keep it that way
 *    if you edit.
 *  - One card on the page (contact), so it reads as the single action.
 *
 * Colours are the app's tokens under the names this page was written with
 * (--paper, --ink, --line ...); see globals.css.
 */
import type { Metadata } from "next";
import Link from "next/link";
import { AboutStats } from "@/components/AboutStats";
import { CopyEmail } from "@/components/CopyEmail";
import { Paragraphs, ProsePage, Rule, SectionLabel } from "@/components/prose";
import { CONTACT_MAILTO } from "@/lib/site";

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

export default function AboutPage() {
  return (
    <ProsePage here="About">
      <h1 className="mb-5 text-[clamp(2rem,6vw,2.85rem)] font-semibold leading-[1.12] tracking-[-0.02em] [text-wrap:balance]">
        I kept losing track of my own applications.
      </h1>
      <p className="m-0 max-w-[56ch] text-[1.1rem] text-[var(--ink-2)]">
        So I built the thing I wanted to exist. StEP1 finds internships worth
        applying to and remembers what happened after you applied.
      </p>

      <Rule />

      <SectionLabel>Why I built it</SectionLabel>
      <Paragraphs>
        <p>
          I&apos;m Aggrey Narh. Most people call me Ussop. I&apos;m a junior at the
          University of Maryland, College Park, studying Information Science with
          a minor in Data Science.
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
      </Paragraphs>

      <Rule />

      <SectionLabel>What it does today</SectionLabel>
      <p className="mb-[18px] max-w-[62ch]">
        StEP1 pulls from community-maintained internship boards, then classifies
        every posting by role and scores it against your profile.
      </p>

      <AboutStats />

      <Paragraphs>
        <p>
          The scoring is a weighted sum, not a black box. Every match tells you
          why it matched: which of your ranked fields it hit, which of your
          skills appear in the posting, how recently it went up. If a score looks
          wrong, you can see exactly which rule made it wrong.
        </p>
        <p>
          The part I use most is the tracker. Applied, heard back, online
          assessment, interview, another round, offer. Every change is a
          timestamped event, so the history stays instead of being overwritten by
          a status column. There&apos;s a state for{" "}
          <strong className="font-semibold">ghosted</strong> too, because that is
          where most applications quietly end up and no tracker I&apos;ve used
          will say so out loud.
        </p>
      </Paragraphs>

      <Rule />

      <SectionLabel>Where it&apos;s going</SectionLabel>
      <p className="mb-[18px] max-w-[62ch]">
        It&apos;s early. Here&apos;s what&apos;s actually next, in the order I
        plan to build it.
      </p>
      <ul className="m-0 flex list-none flex-col p-0">
        {ROADMAP.map((r, i) => (
          <li
            key={r.what}
            className={`flex items-baseline gap-[14px] py-[13px] ${
              i < ROADMAP.length - 1 ? "border-b border-[var(--line)]" : ""
            }`}
          >
            <span className="font-ui min-w-[56px] flex-none rounded-[3px] bg-[var(--accent-soft)] px-[7px] py-[3px] text-center text-[0.66rem] font-semibold uppercase tracking-[0.07em] text-[var(--accent)]">
              {r.when}
            </span>
            <span className="min-w-0">{r.what}</span>
          </li>
        ))}
      </ul>

      <Rule />

      <section className="mt-2 rounded-[4px] border border-[var(--line-2)] bg-[var(--raise)] p-[26px]">
        <SectionLabel>Contact me</SectionLabel>
        <p className="mb-0 max-w-[62ch] text-[0.97rem] text-[var(--ink-2)]">
          Found a bug, want an invite, or think this should do something it
          doesn&apos;t? Send me a note. I read all of them.
        </p>

        <div className="mt-5 flex flex-wrap items-center gap-[10px]">
          <CopyEmail />
        </div>

        <div className="mt-[18px] flex flex-wrap items-center gap-[10px]">
          {/* Opens the visitor's default mail client with To: already filled. */}
          <a
            href={CONTACT_MAILTO}
            className="font-ui inline-block cursor-pointer rounded-[4px] border border-[var(--accent)] bg-[var(--accent)] px-5 py-[11px] text-[0.9rem] font-semibold text-[var(--paper)] no-underline hover:bg-[var(--accent-hover)]"
          >
            Contact me
          </a>
        </div>
      </section>

      <p className="font-ui mt-[52px] border-t border-[var(--line)] pt-5 text-[0.76rem] text-[var(--ink-3)]">
        Built by Aggrey Narh at the University of Maryland. StEP1 stores resumes
        and application history, so there&apos;s a{" "}
        <Link href="/privacy" className="text-[var(--ink-2)] underline underline-offset-2">
          privacy policy
        </Link>{" "}
        worth two minutes of your time.
      </p>
    </ProsePage>
  );
}
