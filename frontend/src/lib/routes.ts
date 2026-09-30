// Addresses inside the site.
//
// The site is served as plain files, so every address has to be one a static
// host can answer without running code. A timeline is therefore addressed
// with a query string, /application?id=12, which is one file for every id.
// Older links in the form /applications/12 have no file. The host serves the
// not-found page for them, and that page sends them on: see `legacyTarget`.

/** Every page that exists as a file. */
export const PAGES = [
  "/",
  "/login",
  "/auth/callback",
  "/onboarding",
  "/onboarding/building",
  "/saved",
  "/applications",
  "/application",
  "/about",
  "/privacy",
  "/review",
  "/admin",
] as const;

export function applicationHref(id: number | string): string {
  return `/application?id=${encodeURIComponent(String(id))}`;
}

/** The id in an old-style /applications/12 address, or null. */
export function legacyApplicationId(pathname: string): string | null {
  const m = pathname.match(/^\/applications\/([^/]+)\/?$/);
  return m ? decodeURIComponent(m[1]) : null;
}

/**
 * Where an address that has no file of its own should go instead, or null
 * if it really is unknown.
 *   /applications/12   ->  /application?id=12   (links from before the move)
 *   /saved/            ->  /saved               (a stray trailing slash)
 *   /about.html        ->  /about
 */
export function legacyTarget(pathname: string, search = ""): string | null {
  const id = legacyApplicationId(pathname);
  if (id) return applicationHref(id);
  const trimmed = pathname.replace(/\.html$/, "").replace(/\/+$/, "") || "/";
  if (trimmed !== pathname && (PAGES as readonly string[]).includes(trimmed)) return trimmed + search;
  return null;
}
