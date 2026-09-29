// The site's security headers and Content-Security-Policy, defined once.
//
// The production site is plain files on a static host, so nothing in the
// app can set a response header. The policy is therefore delivered twice,
// and both copies come from this file:
//
//   1. As response headers, by the host. `npm run headers:amplify` writes
//      them into ../amplify.yml. These are the same for every environment:
//      they name no domain.
//   2. As a <meta http-equiv="Content-Security-Policy"> tag in every page,
//      written at build time by app/layout.tsx. This copy knows the
//      environment: it lists exactly the origins the build was configured
//      with (the API, the upload bucket, the sign-in service).
//
// A browser enforces both, so a request has to be allowed by each. The
// header says "this site, over HTTPS"; the tag narrows that to the exact
// origins. Changing an environment variable and rebuilding is enough: there
// is nothing to edit by hand and nothing that can drift.
//
// `next dev` serves the header copy itself (next.config.ts).

/** "https://api.example.org/x" -> "https://api.example.org"; anything that
 *  isn't an absolute http(s) URL (unset, "mock") -> null. */
export function originOf(value) {
  if (!value) return null;
  try {
    const u = new URL(value);
    return u.protocol === "http:" || u.protocol === "https:" ? u.origin : null;
  } catch {
    return null;
  }
}

/**
 * The origins the browser may call, from the build's configuration.
 * @param {Record<string, string | undefined>} env
 * @returns {string[]}
 */
export function connectOrigins(env) {
  return [
    originOf(env.NEXT_PUBLIC_API_BASE),
    originOf(env.NEXT_PUBLIC_UPLOAD_ORIGIN),
    // Only in cognito mode: the token endpoint is called from the browser.
    env.NEXT_PUBLIC_AUTH_MODE === "cognito" ? originOf(env.NEXT_PUBLIC_COGNITO_DOMAIN) : null,
  ].filter((o, i, all) => o && all.indexOf(o) === i);
}

/** What the header copy allows for connections when no origins are given:
 *  any HTTPS origin. The <meta> copy narrows it to the real ones. */
export const ANY_HTTPS = ["https:"];

/**
 * @param {object} o
 * @param {boolean} [o.dev]       true under `next dev`
 * @param {string[]} o.connect    origins (or schemes) allowed in connect-src, besides 'self'
 * @param {boolean} [o.meta]      true for the <meta> copy, which can't carry frame-ancestors
 */
export function contentSecurityPolicy({ dev = false, connect, meta = false }) {
  const directives = {
    "default-src": ["'self'"],
    // 'unsafe-inline' for scripts: Next writes the data each page needs to
    // start (the React Server Components payload) into inline <script> tags.
    // The pages are static files, so there is no request in which to mint a
    // nonce, and the payload differs per page and per build, so it can't be
    // listed by hash in one header. Without this the pages load but never
    // become interactive. No eval in production.
    // Dev only: 'unsafe-eval', which React uses to rebuild error stacks.
    "script-src": ["'self'", "'unsafe-inline'", ...(dev ? ["'unsafe-eval'"] : [])],
    // Styles come from the site's own stylesheet. Dev injects <style> tags
    // for hot reload, so dev alone allows inline styles.
    "style-src": ["'self'", ...(dev ? ["'unsafe-inline'"] : [])],
    "img-src": ["'self'", "data:"],
    "font-src": ["'self'"],
    // Dev adds the hot-reload websocket.
    "connect-src": ["'self'", ...connect, ...(dev ? ["ws:"] : [])],
    "object-src": ["'none'"],
    // Signing in with Cognito leaves the site by navigation, which a
    // Content-Security-Policy does not govern; nothing is needed for it here.
    ...(meta ? {} : { "frame-ancestors": ["'none'"] }),
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
  };
  return Object.entries(directives)
    .map(([name, values]) => `${name} ${[...new Set(values)].join(" ")}`)
    .join("; ");
}

/**
 * The response headers.
 * @param {object} [o]
 * @param {boolean} [o.dev]
 * @param {string[]} [o.connect]  exact origins; leave out for "any HTTPS origin"
 * @returns {{ key: string, value: string }[]}
 */
export function securityHeaders({ dev = false, connect } = {}) {
  return [
    { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
    { key: "Content-Security-Policy", value: contentSecurityPolicy({ dev, connect: connect ?? ANY_HTTPS }) },
  ];
}

/**
 * The content of the <meta http-equiv="Content-Security-Policy"> tag.
 * @param {Record<string, string | undefined>} env
 */
export function metaPolicy(env) {
  return contentSecurityPolicy({ dev: env.NODE_ENV !== "production", connect: connectOrigins(env), meta: true });
}
