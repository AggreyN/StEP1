import { defineConfig, devices } from "@playwright/test";

// The production suite: the site as it will be hosted.
//
// It builds the static export and serves the files with
// scripts/static-server.mjs, which applies the rewrite rules exactly as they
// are entered in Amplify (amplify-rewrites.json) and the security headers
// from the one definition (security-headers.mjs). Nothing here uses a Next
// server.
//
//   npm run test:prod
//
// Ports and directories of its own, so it never touches what is being served
// on port 3000.
export const SITE = { port: 3200, dir: ".next-export" };

export default defineConfig({
  testDir: "./tests-prod",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : [["list"]],
  timeout: 90_000,
  expect: { timeout: process.env.CI ? 15_000 : 10_000 },
  use: { trace: "on-first-retry" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    {
      name: "mobile",
      use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true },
    },
  ],
  webServer: [
    {
      command: `node scripts/build-export.mjs && node scripts/static-server.mjs --dir ${SITE.dir} --port ${SITE.port}`,
      url: `http://localhost:${SITE.port}/login`,
      reuseExistingServer: false,
      timeout: 300_000,
      env: { NEXT_PUBLIC_API_BASE: "mock", NEXT_DIST_DIR: SITE.dir },
    },
  ],
});
