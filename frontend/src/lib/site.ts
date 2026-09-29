// Facts about the site that more than one page states. Keep them here so
// they are corrected in one place.

export const CONTACT_EMAIL = "ayertey.narh.24@gmail.com";

/** Prefilled so replies land in one thread instead of a nameless inbox. */
export const CONTACT_MAILTO =
  `mailto:${CONTACT_EMAIL}` +
  `?subject=${encodeURIComponent("StEP1")}` +
  `&body=${encodeURIComponent("Hi Aggrey,\n\n")}`;

export const SOURCES = [
  { name: "SimplifyJobs", url: "https://github.com/SimplifyJobs/Summer2027-Internships" },
  { name: "vanshb03", url: "https://github.com/vanshb03/Summer2027-Internships" },
];

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
