import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Playwright runs its own `next dev` on :3100 with NEXT_DIST_DIR=.next-test so
  // it never shares (or overwrites) the build a real server on :3000 is using.
  // Next 16 also holds a per-distDir lockfile, so a shared dir would block.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  devIndicators: { position: "bottom-right" },
};

export default nextConfig;
