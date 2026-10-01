// Leaving a review, and the owner's page for reading them.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { errorNote, expectNoHorizontalScroll, freshEmail, signIn, signInDemo } from "./helpers";

async function signInNonAdmin(page: Page) {
  // A returning student with a profile, who is not the owner.
  await signIn(page, freshEmail("reviewer"), "register");
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByLabel("Major").fill("Information Science");
  for (const n of ["+ Security", "+ Software Engineering", "+ Research"]) {
    await page.getByRole("button", { name: n }).click();
  }
  await page.getByTestId("submit-profile").click();
  await expect(page).toHaveURL(/\/$/, { timeout: 15_000 });
}

async function expectAccessible(page: Page, screen: string) {
  await page.evaluate(() => document.fonts.ready);
  const { violations } = await new AxeBuilder({ page }).analyze();
  expect(
    violations.map((v) => ({ rule: v.id, help: v.help, nodes: v.nodes.slice(0, 3).map((n) => n.target.join(" ")) })),
    `${screen}: accessibility violations`
  ).toEqual([]);
}

const sent = (page: Page) =>
  page.evaluate(() => {
    const w = window as unknown as { __step1Requests?: string[]; __step1Bodies?: unknown[] };
    return (w.__step1Requests ?? [])
      .map((line, i) => ({ line, body: (w.__step1Bodies ?? [])[i] }))
      .filter((r) => r.line.startsWith("POST /reviews"));
  });

test.describe("leaving a review", () => {
  test("found from the footer and the Profile page, not from the tab bar", async ({ page }) => {
    await signInNonAdmin(page);
    const footer = page.getByRole("contentinfo");
    await expect(footer.getByRole("link", { name: "Leave a review" })).toHaveAttribute("href", "/review");
    await page.goto("/onboarding");
    await expect(page.getByTestId("profile-feedback").getByRole("link", { name: "Leave a review" })).toHaveAttribute(
      "href",
      "/review"
    );
    await page.getByTestId("profile-feedback").getByRole("link", { name: "Leave a review" }).click();
    await expect(page).toHaveURL(/\/review$/);
    await expect(page.getByRole("heading", { name: "Leave a review" })).toBeVisible();
    // signed-out pages don't offer it
    await page.goto("/about");
    await expect(page.getByRole("contentinfo").getByRole("link", { name: "Leave a review" })).toHaveCount(0);
  });

  test("says where it goes, validates, sends, and thanks", async ({ page }) => {
    await signInDemo(page);
    await page.goto("/review");
    await expect(page.getByTestId("review-notice")).toContainText("goes to Aggrey");
    await expect(page.getByTestId("review-notice")).toContainText("demo@umd.edu");
    const send = page.getByTestId("send-review");
    const box = page.getByRole("textbox", { name: "Your review" });

    // no rating, no text
    await expect(send).toBeDisabled();
    await expect(page.getByTestId("review-hint")).toHaveText("Choose a rating to send.");
    // text but no rating
    await box.fill("Useful so far.");
    await expect(send).toBeDisabled();
    // rating but blank text
    await page.getByRole("radio", { name: "4 stars" }).click();
    await expect(page.getByTestId("rating-text")).toHaveText("4 stars out of 5");
    await box.fill("   \n  ");
    await expect(send).toBeDisabled();
    await expect(page.getByTestId("review-hint")).toHaveText("Write a few words to send.");
    // too long
    await box.fill("x".repeat(2001));
    await expect(page.getByTestId("review-count")).toHaveText("2,001 of 2,000 characters. That is 1 too many.");
    await expect(send).toBeDisabled();
    await box.fill("x".repeat(2000));
    await expect(page.getByTestId("review-count")).toHaveText("2,000 of 2,000 characters");
    await expect(send).toBeEnabled();

    await box.fill("  The timeline is great.\nPlease add reminders.  ");
    await send.click();
    await expect(page.getByTestId("review-sent")).toContainText("Thank you. Your review is on its way to Aggrey.");
    await expect(page.getByRole("textbox", { name: "Your review" })).toHaveCount(0);
    const posted = await sent(page);
    expect(posted.map((p) => p.body)).toEqual([{ rating: 4, body: "The timeline is great.\nPlease add reminders." }]);
    await page.getByRole("link", { name: "Back to Matches" }).click();
    await expect(page).toHaveURL(/\/$/);
  });

  test("a rate limit shows the API's words and keeps what was written", async ({ page }) => {
    await signInDemo(page);
    await page.goto("/review");
    await page.getByRole("radio", { name: "2 stars" }).click();
    await page.getByRole("textbox", { name: "Your review" }).fill("Second thoughts.");
    await page.evaluate(() => localStorage.setItem("step1.mock.fail", "429 POST /reviews"));
    await page.getByTestId("send-review").click();
    await expect(errorNote(page)).toHaveText("You've sent a lot of reviews today. Try again tomorrow.");
    await expect(page.getByRole("textbox", { name: "Your review" })).toHaveValue("Second thoughts.");
    await expect(page.getByTestId("review-sent")).toHaveCount(0);
    expect(await page.evaluate(() => localStorage.getItem("step1.token"))).not.toBeNull();
  });

  test("the rating works from the keyboard alone", async ({ page }) => {
    await signInDemo(page);
    await page.goto("/review");
    const stars = page.getByRole("radio");
    await expect(stars).toHaveCount(5);
    await expect(stars).toHaveText(["", "", "", "", ""]);
    for (const [i, name] of ["1 star", "2 stars", "3 stars", "4 stars", "5 stars"].entries()) {
      await expect(stars.nth(i)).toHaveAccessibleName(name);
    }
    // one tab stop: the first star before anything is chosen
    for (let i = 0; i < 40 && !(await stars.first().evaluate((el) => el === document.activeElement)); i++) {
      await page.keyboard.press("Tab");
    }
    await expect(stars.first()).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect(page.getByRole("radio", { name: "1 star" })).toHaveAttribute("aria-checked", "true");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await expect(page.getByRole("radio", { name: "3 stars" })).toBeFocused();
    await expect(page.getByRole("radio", { name: "3 stars" })).toHaveAttribute("aria-checked", "true");
    await expect(page.getByTestId("rating-text")).toHaveText("3 stars out of 5");
    await page.keyboard.press("End");
    await expect(page.getByRole("radio", { name: "5 stars" })).toHaveAttribute("aria-checked", "true");
    await page.keyboard.press("ArrowRight"); // stays at 5
    await expect(page.getByRole("radio", { name: "5 stars" })).toHaveAttribute("aria-checked", "true");
    await page.keyboard.press("ArrowLeft");
    await expect(page.getByRole("radio", { name: "4 stars" })).toHaveAttribute("aria-checked", "true");
    // Tab leaves the group in one step, to the text box
    await page.keyboard.press("Tab");
    await expect(page.getByRole("textbox", { name: "Your review" })).toBeFocused();
    await page.keyboard.type("Typed with the keyboard.");
    await page.keyboard.press("Tab");
    await expect(page.getByTestId("send-review")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("review-sent")).toBeVisible();
  });
});

test.describe("the admin page", () => {
  test("the owner sees every review, the count and the average", async ({ page }) => {
    await signInDemo(page);
    // write one first, so the newest is known
    await page.goto("/review");
    await page.getByRole("radio", { name: "5 stars" }).click();
    await page.getByRole("textbox", { name: "Your review" }).fill("First line.\nSecond line <b>not bold</b>.");
    await page.getByTestId("send-review").click();
    await expect(page.getByTestId("review-sent")).toBeVisible();

    const nav = page.getByRole("navigation", { name: "Main" }).first();
    await nav.getByRole("link", { name: "Admin" }).click();
    await expect(page).toHaveURL(/\/admin$/);
    await expect(page.getByRole("heading", { name: "Reviews" })).toBeVisible();
    await expect(page.getByTestId("review-total")).toHaveText("13");
    // fixture ratings 5,4,2,5,3,1,4,5,3,4,2,5 plus the new 5: 48 / 13
    await expect(page.getByTestId("review-average")).toHaveText("3.7out of 5");

    const reviews = page.getByTestId("admin-review");
    await expect(reviews).toHaveCount(13);
    const newest = reviews.first();
    await expect(newest.getByRole("img", { name: "5 out of 5 stars" })).toBeVisible();
    // plain text, line breaks kept, markup shown as typed
    await expect(newest.getByTestId("admin-review-body")).toHaveText("First line.\nSecond line <b>not bold</b>.");
    expect(await newest.locator("b").count()).toBe(0);
    expect(await newest.getByTestId("admin-review-body").evaluate((el) => getComputedStyle(el).whiteSpace)).toBe("pre-wrap");
    await expect(newest.getByTestId("admin-review-author")).toContainText("demo@umd.edu");

    // newest first
    const times = await reviews.locator("time").evaluateAll((els) => els.map((e) => e.getAttribute("datetime")!));
    expect(times).toEqual([...times].sort().reverse());
    // a deleted account, and an account with no display name (email only)
    await expect(page.getByTestId("admin-review-author").filter({ hasText: "Deleted account" })).toHaveCount(1);
    await expect(page.getByTestId("admin-review-author").filter({ hasText: "j.okafor@umd.edu" })).toHaveText(
      "j.okafor@umd.edu"
    );
  });

  test("load more follows has_more", async ({ page }) => {
    await signInDemo(page);
    // 25 reviews: more than one page of 20
    await page.evaluate(() => {
      const key = "step1.mock.v4";
      const state = JSON.parse(localStorage.getItem(key)!);
      state.reviews = Array.from({ length: 13 }, (_, i) => ({
        id: 5000 + i,
        rating: (i % 5) + 1,
        body: `Seeded review ${i + 1}`,
        created_at: new Date(Date.now() - 60_000 * (13 - i)).toISOString(),
        user: { email: "demo@umd.edu", display_name: "Demo Terp" },
      }));
      localStorage.setItem(key, JSON.stringify(state));
    });
    await page.goto("/admin");
    const reviews = page.getByTestId("admin-review");
    await expect(page.getByTestId("review-total")).toHaveText("25");
    await expect(reviews).toHaveCount(20);
    await expect(reviews.first()).toContainText("Seeded review 13");
    await page.getByTestId("load-more-reviews").click();
    await expect(reviews).toHaveCount(25);
    await expect(page.getByTestId("load-more-reviews")).toHaveCount(0);
  });

  test("the Admin link is on the Profile page, for phones", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await signInDemo(page);
    await expect(page.getByRole("navigation", { name: "Main" }).last().getByRole("link")).toHaveCount(4);
    await page.goto("/onboarding");
    await page.getByTestId("profile-admin-link").click();
    await expect(page).toHaveURL(/\/admin$/);
    await expect(page.getByTestId("admin-review").first()).toBeVisible();
  });

  test("anyone else gets the not-found page and no Admin link", async ({ page }) => {
    await signInNonAdmin(page);
    await expect(page.getByTestId("posting-card").first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);
    await page.goto("/onboarding");
    await expect(page.getByTestId("profile-feedback")).toBeVisible();
    await expect(page.getByTestId("profile-admin-link")).toHaveCount(0);

    await page.goto("/admin");
    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
    await expect(page.getByTestId("admin-review")).toHaveCount(0);
    await expect(page).toHaveURL(/\/admin$/);
  });

  test("if the API says 404, the admin page says not found too", async ({ page }) => {
    await signInDemo(page);
    await page.evaluate(() => localStorage.setItem("step1.mock.fail", "404 GET /admin/reviews"));
    await page.goto("/admin");
    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  });
});

for (const scheme of ["light", "dark"] as const) {
  for (const width of [1280, 375]) {
    test(`/review and /admin are accessible and fit (${scheme}, ${width}px)`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ colorScheme: scheme });
      await signInDemo(page);

      await page.goto("/review");
      await expect(page.getByTestId("star-rating")).toBeVisible();
      await expectAccessible(page, "review, empty");
      await expectNoHorizontalScroll(page);
      await page.getByRole("radio", { name: "3 stars" }).click();
      await page.getByRole("textbox", { name: "Your review" }).fill("x".repeat(2001));
      await expectAccessible(page, "review, too long");
      await page.getByRole("textbox", { name: "Your review" }).fill("Fine.");
      await page.getByTestId("send-review").click();
      await expect(page.getByTestId("review-sent")).toBeVisible();
      await expectAccessible(page, "review, sent");

      await page.goto("/admin");
      await expect(page.getByTestId("admin-review").first()).toBeVisible();
      await expectAccessible(page, "admin");
      await expectNoHorizontalScroll(page);

      expect(await page.locator("body").innerText()).not.toContain("—");
    });
  }
}
