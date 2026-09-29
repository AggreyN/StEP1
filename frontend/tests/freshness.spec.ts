// The "how fresh are the listings" line on the dashboard.
import { expect, test, type Page } from "@playwright/test";
import { describeFreshness, everyInterval, timeAgo } from "../src/lib/freshness";
import type { IngestStatus } from "../src/lib/types";
import { expectNoHorizontalScroll, signInDemo } from "./helpers";

async function showScenario(page: Page, scenario: string) {
  await page.evaluate((s) => localStorage.setItem("step1.mock.ingest", s), scenario);
  await page.reload();
  await expect(page.getByTestId("posting-card").first()).toBeVisible();
}

const asked = (page: Page) =>
  page.evaluate(() =>
    ((window as unknown as { __step1Requests?: string[] }).__step1Requests ?? []).includes("GET /ingest/status")
  );

test.describe("on the dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await signInDemo(page);
  });

  test("fresh: says when listings were updated and how often they refresh", async ({ page }) => {
    const line = page.getByTestId("freshness");
    await expect(line).toHaveText("Listings updated 3 hours ago · refreshes every 24 hours");
    await expect(line).toHaveAttribute("data-tone", "quiet");
    await expect(line).toHaveAttribute("title", /4,781 open listings/);
    // it sits with the heading, above the cards
    const lineBox = await line.boundingBox();
    const cardBox = await page.getByTestId("posting-card").first().boundingBox();
    expect(lineBox!.y).toBeLessThan(cardBox!.y);
  });

  test("running: says an update is in progress", async ({ page }) => {
    await showScenario(page, "running");
    await expect(page.getByTestId("freshness")).toHaveText("Updating listings now…");
    await expect(page.getByTestId("freshness")).toHaveAttribute("data-tone", "busy");
  });

  test("never run: says listings haven't been loaded", async ({ page }) => {
    await showScenario(page, "never");
    await expect(page.getByTestId("freshness")).toHaveText("Listings haven't been loaded yet");
    await expect(page.getByTestId("freshness")).toHaveAttribute("data-tone", "quiet");
  });

  test("stale: warns calmly that a refresh is overdue", async ({ page }) => {
    await showScenario(page, "stale");
    const line = page.getByTestId("freshness");
    await expect(line).toHaveText("Listings last updated 3 days ago · a refresh is overdue");
    await expect(line).toHaveAttribute("data-tone", "warn");
  });

  test("failed: warns that the last refresh failed, without alarm styling", async ({ page }) => {
    await showScenario(page, "failed");
    const line = page.getByTestId("freshness");
    await expect(line).toHaveText("Listings last updated 3 days ago · the last refresh failed");
    await expect(line).toHaveAttribute("data-tone", "warn");
    await expect(line).toHaveAttribute("title", /simplify: HTTP 503/);

    // visible: not the faint grey of the normal line…
    const warnColor = await line.evaluate((el) => getComputedStyle(el).color);
    await showScenario(page, "fresh");
    const quietColor = await page.getByTestId("freshness").evaluate((el) => getComputedStyle(el).color);
    expect(warnColor).not.toBe(quietColor);
    // …but calm: amber text on the page background, not the error red, no filled banner
    await showScenario(page, "failed");
    const style = await line.evaluate((el) => {
      const cs = getComputedStyle(el);
      const probe = document.createElement("span");
      probe.style.color = "var(--danger)";
      document.body.append(probe);
      const danger = getComputedStyle(probe).color;
      probe.remove();
      return { color: cs.color, background: cs.backgroundColor, danger };
    });
    expect(style.color).not.toBe(style.danger);
    expect(style.background).toBe("rgba(0, 0, 0, 0)");
    await expect(page.locator('[role="alert"]:not(#__next-route-announcer__)')).toHaveCount(0);
  });

  test("one source failing is reported as a partial failure", async ({ page }) => {
    await showScenario(page, "partial");
    await expect(page.getByTestId("freshness")).toHaveText(
      "Listings last updated 3 hours ago · part of the last refresh failed"
    );
    await expect(page.getByTestId("freshness")).toHaveAttribute("data-tone", "warn");
  });

  test("auto off: drops the refresh schedule", async ({ page }) => {
    await showScenario(page, "manual");
    await expect(page.getByTestId("freshness")).toHaveText("Listings updated 5 hours ago");
  });

  test("endpoint missing: shows nothing and the dashboard still works", async ({ page }) => {
    await showScenario(page, "error");
    await expect.poll(() => asked(page)).toBe(true);
    await expect(page.getByTestId("posting-card")).toHaveCount(20);
    await expect(page.getByTestId("freshness")).toHaveCount(0);
    await expect(page.locator('[role="alert"]:not(#__next-route-announcer__)')).toHaveCount(0);
    await expect(page.getByTestId("feed-total")).toHaveText("52 postings, newest first");
    // still signed in and usable
    await page.getByRole("radio", { name: "Best match" }).click();
    await expect(page).toHaveURL(/sort=score/);
    await expect(page.getByTestId("posting-card")).toHaveCount(20);
  });

  test("the line stays put when filters empty the feed", async ({ page }) => {
    await page.goto("/?location=Anchorage");
    await expect(page.getByTestId("empty-state")).toBeVisible();
    await expect(page.getByTestId("freshness")).toHaveText(/^Listings updated 3 hours ago/);
  });
});

test.describe("at 375px", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("the longest line wraps instead of widening the page", async ({ page }) => {
    await signInDemo(page);
    await showScenario(page, "partial");
    await expect(page.getByTestId("freshness")).toBeVisible();
    await expectNoHorizontalScroll(page);
    await showScenario(page, "fresh");
    await expect(page.getByTestId("freshness")).toBeVisible();
    await expectNoHorizontalScroll(page);
  });
});

test.describe("wording rules", () => {
  const NOW = Date.parse("2026-09-28T21:00:00Z");
  const hoursAgo = (h: number) => new Date(NOW - h * 3_600_000).toISOString();
  const status = (over: Partial<IngestStatus>): IngestStatus => ({
    last_success_at: hoursAgo(3),
    next_due_at: null,
    interval_hours: 24,
    auto: true,
    running: false,
    active_postings: 100,
    sources: [],
    ...over,
  });
  const source = (error: string | null) => ({
    source: "simplify",
    last_success_at: null,
    last_attempt_at: null,
    fetched: 0,
    upserted: 0,
    deactivated: 0,
    error,
  });

  test("stale means older than twice the interval, not equal to it", () => {
    expect(describeFreshness(status({ last_success_at: hoursAgo(48) }), NOW).tone).toBe("quiet");
    expect(describeFreshness(status({ last_success_at: hoursAgo(48.1) }), NOW).tone).toBe("warn");
    expect(describeFreshness(status({ last_success_at: hoursAgo(13), interval_hours: 6 }), NOW)).toEqual({
      tone: "warn",
      text: "Listings last updated 13 hours ago · a refresh is overdue",
    });
  });

  test("running wins over everything else", () => {
    const s = status({ running: true, last_success_at: null, sources: [source("boom")] });
    expect(describeFreshness(s, NOW)).toEqual({ tone: "busy", text: "Updating listings now…" });
  });

  test("never loaded and failing says both", () => {
    const s = status({ last_success_at: null, sources: [source("boom")] });
    expect(describeFreshness(s, NOW)).toEqual({
      tone: "warn",
      text: "Listings haven't been loaded yet · the last refresh failed",
    });
  });

  test("old listings with auto off are flagged without claiming a schedule", () => {
    const s = status({ auto: false, last_success_at: hoursAgo(24 * 5) });
    expect(describeFreshness(s, NOW)).toEqual({ tone: "warn", text: "Listings last updated 5 days ago" });
  });

  test("relative times and intervals read naturally", () => {
    expect(timeAgo(hoursAgo(0), NOW)).toBe("just now");
    expect(timeAgo(hoursAgo(-0.5), NOW)).toBe("just now"); // server clock ahead
    expect(timeAgo(hoursAgo(1 / 60), NOW)).toBe("1 minute ago");
    expect(timeAgo(hoursAgo(0.75), NOW)).toBe("45 minutes ago");
    expect(timeAgo(hoursAgo(1), NOW)).toBe("1 hour ago");
    expect(timeAgo(hoursAgo(23.9), NOW)).toBe("23 hours ago");
    expect(timeAgo(hoursAgo(24), NOW)).toBe("1 day ago");
    expect(timeAgo(hoursAgo(71), NOW)).toBe("2 days ago");
    expect(everyInterval(1)).toBe("every hour");
    expect(everyInterval(6)).toBe("every 6 hours");
    expect(everyInterval(24)).toBe("every 24 hours");
    expect(everyInterval(48)).toBe("every 2 days");
  });
});
