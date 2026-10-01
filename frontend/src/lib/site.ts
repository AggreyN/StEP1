// Facts about the site that more than one page states. Keep them here so
// they are corrected in one place.

export const CONTACT_EMAIL = "ayertey.narh.24@gmail.com";

/** Prefilled so replies land in one thread instead of a nameless inbox. */
export const CONTACT_MAILTO =
  `mailto:${CONTACT_EMAIL}` +
  `?subject=${encodeURIComponent("StEP1")}` +
  `&body=${encodeURIComponent("Hi Aggrey,\n\n")}`;

/** Every list the listings come from, credited by name wherever listings are
 *  shown. Keep in step with the sources the API actually reads. */
export const SOURCES = [
  { name: "SimplifyJobs Summer 2027 Internships", short: "SimplifyJobs", url: "https://github.com/SimplifyJobs/Summer2027-Internships" },
  { name: "SimplifyJobs New Grad Positions", short: "SimplifyJobs", url: "https://github.com/SimplifyJobs/New-Grad-Positions" },
  { name: "vanshb03 Summer 2027 Internships", short: "vanshb03", url: "https://github.com/vanshb03/Summer2027-Internships" },
  { name: "Jobright Data Analysis Internships", short: "Jobright", url: "https://github.com/jobright-ai/2026-Data-Analysis-Internship" },
  { name: "Jobright Business Analyst Internships", short: "Jobright", url: "https://github.com/jobright-ai/2026-Business-Analyst-Internship" },
  { name: "Jobright Product Management Internships", short: "Jobright", url: "https://github.com/jobright-ai/2026-Product-Management-Internship" },
  { name: "SpeedyApply 2027 AI College Jobs", short: "SpeedyApply", url: "https://github.com/speedyapply/2027-AI-College-Jobs" },
  { name: "Zapply Internships 2027", short: "Zapply", url: "https://github.com/zapplyjobs/Internships-2027" },
];

/** A posting's `source` as a reader would say it. New sources the API adds
 *  later fall through to a tidied version of their own name. */
export function sourceLabel(source: string): string {
  const s = source.toLowerCase();
  if (s.startsWith("simplify")) return "SimplifyJobs";
  if (s.startsWith("vansh")) return "vanshb03";
  if (s.startsWith("jobright")) return "Jobright";
  if (s.startsWith("speedyapply")) return "SpeedyApply";
  if (s.startsWith("zapply")) return "Zapply";
  const tidy = source.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  return tidy ? tidy.charAt(0).toUpperCase() + tidy.slice(1) : "another list";
}

/* ==========================================================================
   HOSTING: CHECK BEFORE LAUNCH
   These sentences appear on the Privacy page. They describe where data
   lives and how it is protected, so they must match the deployment as it
   actually is on launch day. If the region, the provider, the bucket
   settings or the database encryption differ, correct them here.
   ========================================================================== */
export const HOSTING = {
  site: "The hosted site runs on Amazon Web Services in the United States.",
  resumes: "Resumes sit in a private, encrypted storage bucket and are never public.",
  database: "The database is encrypted at rest.",
};

/** Shown on the Privacy page. Update when the policy text changes. */
export const PRIVACY_LAST_UPDATED = "September 28, 2026";
