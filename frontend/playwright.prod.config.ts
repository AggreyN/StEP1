import { defineConfig, devices } from "@playwright/test";

// Runs the production build (`next build && next start`) under the real
// security headers, on its own port and in its own build directory, so it
// never touches what `npm run dev` or `npm start` are serving on port 3000.
//
//   npm run test:prod
const PORT = 3200;

export default defineConfig({
  testDir: "./tests-prod",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : [["list"]],
  timeout: 90_000,
  expect: { timeout: 10_000 },
  use: { baseURL: `http://localhost:${PORT}`, trace: "on-first-retry" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    {
      name: "mobile",
      use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true },
    },
  ],
  webServer: {
    command: `npx next build && npx next start --port ${PORT}`,
    url: `http://localhost:${PORT}/login`,
    reuseExistingServer: false,
    timeout: 300_000,
    env: { NEXT_PUBLIC_API_BASE: "mock", NEXT_DIST_DIR: ".next-prod" },
  },
});
