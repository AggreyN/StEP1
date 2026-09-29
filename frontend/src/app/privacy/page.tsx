/**
 * StEP1: Privacy.  Route: /privacy  (public, no sign-in)
 *
 * Same rules as the About page: plain English, no em dashes, nothing that
 * isn't true of the app as it is. If the app starts collecting something
 * new, or stops, this page changes in the same commit.
 *
 * The hosting sentences come from HOSTING in lib/site.ts so they can be
 * corrected in one place at launch.
 */
import type { Metadata } from "next";
import { Paragraphs, ProsePage, Rule, SectionLabel } from "@/components/prose";
import { CONTACT_EMAIL, CONTACT_MAILTO, HOSTING, PRIVACY_LAST_UPDATED, SOURCES } from "@/lib/site";

export const metadata: Metadata = {
  title: "Privacy",
  description: "What StEP1 collects, where it lives, who can see it, and how to delete it.",
};

const link = "text-[var(--accent-text)] underline underline-offset-2";

function Items({ children }: { children: React.ReactNode }) {
  return (
    <ul className="m-0 max-w-[62ch] list-disc space-y-2 pl-5 marker:text-[var(--ink-3)]">{children}</ul>
  );
}

export default function PrivacyPage() {
  return (
    <ProsePage here="Privacy">
      <h1 className="mb-5 text-[clamp(2rem,6vw,2.85rem)] font-semibold leading-[1.12] tracking-[-0.02em] [text-wrap:balance]">
        What StEP1 keeps about you, and what it doesn&apos;t.
      </h1>
      <p className="m-0 max-w-[56ch] text-[1.1rem] text-[var(--ink-2)]">
        You are trusting this site with your resume. Here is exactly what that
        means, in about two minutes.
      </p>

      <Rule />

      <SectionLabel>What is collected</SectionLabel>
      <Items>
        <li>Your email address, and a hash of your password. The password itself is never stored.</li>
        <li>
          What you enter on your profile: school, major, minor, degree level,
          graduation year, the terms you want, the locations you prefer, and
          your ranked fields of interest.
        </li>
        <li>Your resume: the file, plus the text and the skills read from it.</li>
        <li>
          What you do here: the postings you save, the applications you track,
          and the events and notes on each one.
        </li>
      </Items>

      <Rule />

      <SectionLabel>What is not</SectionLabel>
      <Paragraphs>
        <p>
          No analytics, no tracking, no ads, and no cookies. When you sign in, a
          sign-in token is kept in your browser&apos;s local storage so you stay
          signed in. Signing out removes it.
        </p>
        <p>Nothing is sold, and nothing is shared with anyone.</p>
      </Paragraphs>

      <Rule />

      <SectionLabel>Where it lives</SectionLabel>
      <p className="m-0 max-w-[62ch]" data-testid="hosting">
        {HOSTING.site} {HOSTING.resumes} {HOSTING.database}
      </p>

      <Rule />

      <SectionLabel>Who can see it</SectionLabel>
      <p className="m-0 max-w-[62ch]">
        I can. I&apos;m Aggrey Narh and I run the site. Nobody else can.
      </p>

      <Rule />

      <SectionLabel>How matching works</SectionLabel>
      <p className="m-0 max-w-[62ch]">
        Every score comes from a fixed rule: a weighted sum of how a posting
        lines up with your ranked fields, your skills, your locations and your
        terms, and how recently it was posted. It is not a model trained on
        your data, and your data is not used to train anything.
      </p>

      <Rule />

      <SectionLabel>Where listings come from</SectionLabel>
      <p className="m-0 max-w-[62ch]">
        Listings come from two community-maintained lists on GitHub,{" "}
        <a className={link} href={SOURCES[0].url} target="_blank" rel="noreferrer">
          {SOURCES[0].name}
        </a>{" "}
        and{" "}
        <a className={link} href={SOURCES[1].url} target="_blank" rel="noreferrer">
          {SOURCES[1].name}
        </a>
        . Every listing links to the original posting, and that is where you
        apply. StEP1 never applies for you.
      </p>

      <Rule />

      <SectionLabel>How to delete everything</SectionLabel>
      <Paragraphs>
        <p>
          Go to Profile, then Delete my account. That removes your account, your
          resume file and all of your history immediately.
        </p>
        <p>
          Or email me and I will do it for you:{" "}
          <a className={link} href={CONTACT_MAILTO}>
            {CONTACT_EMAIL}
          </a>
          . The same address works for any question about this page.
        </p>
      </Paragraphs>

      <p className="font-ui mt-[52px] border-t border-[var(--line)] pt-5 text-[0.76rem] text-[var(--ink-3)]">
        Last updated {PRIVACY_LAST_UPDATED}.
      </p>
    </ProsePage>
  );
}
