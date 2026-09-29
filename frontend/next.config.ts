import type { NextConfig } from "next";
import { securityHeaders } from "./security-headers.mjs";

const nextConfig: NextConfig = {
  // Playwright runs its own `next dev` on :3100 with NEXT_DIST_DIR=.next-test so
  // it never shares (or overwrites) the build a real server on :3000 is using.
  // Next 16 also holds a per-distDir lockfile, so a shared dir would block.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // The dev-tools badge would sit on top of the mobile tab bar. Errors still show.
  devIndicators: false,
  poweredByHeader: false,

  // Security headers on every response. See security-headers.mjs for what
  // each part of the Content-Security-Policy allows and why. The same set is
  // mirrored in ../amplify.yml (npm run headers:amplify).
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders({
          dev: process.env.NODE_ENV !== "production",
          apiBase: process.env.NEXT_PUBLIC_API_BASE,
          uploadOrigin: process.env.NEXT_PUBLIC_UPLOAD_ORIGIN,
        }),
      },
    ];
  },
};

export default nextConfig;
