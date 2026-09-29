import type { NextConfig } from "next";
import { connectOrigins, securityHeaders } from "./security-headers.mjs";

const production = process.env.NODE_ENV === "production";

const nextConfig: NextConfig = {
  // The production build is a static export: plain files that any static host
  // can serve. `next build` writes them to `out/`, or to NEXT_DIST_DIR when
  // that is set (the test suites use their own directories so they never
  // overwrite a build someone is serving).
  output: production ? "export" : undefined,
  distDir: process.env.NEXT_DIST_DIR || (production ? "out" : ".next"),

  // The dev-tools badge would sit on top of the mobile tab bar. Errors still show.
  devIndicators: false,

  // A static export has no server to set headers, so in production they come
  // from the host (see ../amplify.yml, written by `npm run headers:amplify`
  // from the same definition). `next dev` serves them itself, which keeps
  // development under a Content-Security-Policy too.
  ...(production
    ? {}
    : {
        async headers() {
          return [
            {
              source: "/:path*",
              headers: securityHeaders({ dev: true, connect: connectOrigins(process.env) }),
            },
          ];
        },
      }),
};

export default nextConfig;
