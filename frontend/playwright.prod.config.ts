import { defineConfig, devices } from "@playwright/test";
import { OIDC, SITES } from "./tests-prod/support/sites.mjs";

// The production suite: the site as it will be hosted.
//
// It builds the static export three ways (local sign-in, local sign-in with
// registration closed, Cognito sign-in) and serves each as plain files with
// scripts/static-server.mjs, which applies the rewrite rules exactly as they
// are entered in Amplify (amplify-rewrites.json) and the security headers
// from the one definition (security-headers.mjs). Cognito is played by a
// stand-in (tests-prod/support/oidc-stub.mjs). Nothing here uses a Next
// server, AWS, or the network.
//
//   npm run test:prod
//
// Ports 3200, 3201, 3300 and 3400, and build directories of its own, so it
// never touches what is being served on port 3000.
const serve = (site: { dir: string; port: number; connect?: string[] }) =>
  `node scripts/static-server.mjs --dir ${site.dir} --port ${site.port}` +
  (site.connect ? ` --connect ${site.connect.join(",")}` : "");

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
      // Builds all three first, then serves the first. The suite starts when
      // this one answers, so every build is finished by then.
      command: `node tests-prod/support/build-sites.mjs && ${serve(SITES.local)}`,
      url: `http://localhost:${SITES.local.port}/login`,
      reuseExistingServer: false,
      timeout: 600_000,
    },
    {
      command: serve(SITES.closed),
      url: `http://localhost:${SITES.closed.port}/icon.svg`,
      reuseExistingServer: false,
      timeout: 600_000,
    },
    {
      command: serve(SITES.cognito),
      url: `http://localhost:${SITES.cognito.port}/icon.svg`,
      reuseExistingServer: false,
      timeout: 600_000,
    },
    {
      command:
        `node tests-prod/support/oidc-stub.mjs --port ${OIDC.port} --client ${OIDC.client}` +
        ` --redirect ${SITES.cognito.env.NEXT_PUBLIC_COGNITO_REDIRECT_URI}` +
        ` --logout ${SITES.cognito.env.NEXT_PUBLIC_COGNITO_LOGOUT_URI}`,
      url: `http://localhost:${OIDC.port}/__test/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
