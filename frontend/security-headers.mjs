// The site's security headers, in one place. next.config.ts serves them on
// every response, scripts/amplify-headers.mjs writes the same set into
// ../amplify.yml, and the tests read them from here.

/** "https://api.example.com/x" -> "https://api.example.com"; anything that
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
 * @param {object} o
 * @param {boolean} o.dev            true under `next dev`
 * @param {string[]} o.connect       extra origins the browser may call:
 *                                   the API, and the upload host if any
 */
export function contentSecurityPolicy({ dev, connect }) {
  const directives = {
    "default-src": ["'self'"],
    // 'unsafe-inline' for scripts: Next writes the data each page needs to
    // start (the React Server Components payload) into inline <script> tags.
    // These pages are prerendered, so there is no request in which to mint a
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
    "frame-ancestors": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
  };
  return Object.entries(directives)
    .map(([name, values]) => `${name} ${[...new Set(values)].join(" ")}`)
    .join("; ");
}

/**
 * @param {object} [o]
 * @param {boolean} [o.dev]
 * @param {string}  [o.apiBase]       NEXT_PUBLIC_API_BASE
 * @param {string}  [o.uploadOrigin]  NEXT_PUBLIC_UPLOAD_ORIGIN (the S3 host resumes are PUT to)
 * @param {string[]} [o.connect]      used instead of the two above when given
 * @returns {{ key: string, value: string }[]}
 */
export function securityHeaders({ dev = false, apiBase, uploadOrigin, connect } = {}) {
  const origins = connect ?? [originOf(apiBase), originOf(uploadOrigin)].filter(Boolean);
  return [
    { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
    { key: "Content-Security-Policy", value: contentSecurityPolicy({ dev, connect: origins }) },
  ];
}
