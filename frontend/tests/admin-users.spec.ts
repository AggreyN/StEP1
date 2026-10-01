// The owner's Users tab and each person's page.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { errorNote, expectNoHorizontalScroll, freshEmail, signIn, signInDemo } from "./helpers";

async function expectAccessible(page: Page, screen: string) {
  await page.evaluate(() => document.fonts.ready);
  const { violations } = await new AxeBuilder({ page }).analyze();
  expect(
    violations.map((v) => ({ rule: v.id, help: v.help, nodes: v.nodes.slice(0, 3).map((n) => n.target.join(" ")) })),
    `${screen}: accessibility violations`
  ).toEqual([]);
}

test("the Users tab lists everyone, searches, and loads more", async ({ page }) => {
  await signInDemo(page);
  await page.goto("/admin");
  await page.getByRole("navigation", { name: "Admin sections" }).getByRole("link", { name: "Users" }).click();
  await expect(page).toHaveURL(/\/admin\?tab=users$/);
  await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();

  const rows = page.getByTestId("person-row");
  // demo@umd.edu plus twenty-four fictional students
  await expect(page.getByTestId("people-total")).toHaveText("25 people");
  await expect(rows).toHaveCount(20);
  await expect(rows.first()).toContainText("demo@umd.edu");
  await page.getByTestId("load-more-people").click();
  await expect(rows).toHaveCount(25);
  await expect(page.getByTestId("load-more-people")).toHaveCount(0);

  // search by name, by school, by major; it lands in the URL and survives a reload
  await page.getByTestId("people-search").fill("towson");
  await expect(page).toHaveURL(/q=towson/);
  const towson = await rows.count();
  expect(towson).toBeGreaterThan(0);
  for (const row of await rows.all()) await expect(row).toContainText("Towson University");
  await page.reload();
  await expect(page.getByTestId("people-search")).toHaveValue("towson");
  await expect(rows).toHaveCount(towson);

  await page.getByTestId("people-search").fill("zzz-nobody");
  await expect(page.getByText("Nobody matches that search.")).toBeVisible();
});

test("a person's page shows their data as plain text, with a clear banner", async ({ page }) => {
  // A real student in this browser: a profile, a saved posting, an application, a review.
  const email = freshEmail("subject");
  await signIn(page, email, "register");
  await page.getByLabel("Major").fill("Information Science");
  for (const n of ["+ Security", "+ Software Engineering", "+ Research"]) {
    await page.getByRole("button", { name: n }).click();
  }
  await page.getByTestId("submit-profile").click();
  await expect(page).toHaveURL(/\/$/, { timeout: 15_000 });
  await page.goto("/review");
  await page.getByRole("radio", { name: "3 stars" }).click();
  await page.getByRole("textbox", { name: "Your review" }).fill("Line one.\n<script>alert(1)</script>");
  await page.getByTestId("send-review").click();
  await expect(page.getByTestId("review-sent")).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();

  await signInDemo(page);
  await page.goto("/admin?tab=users");
  await page.getByTestId("people-search").fill(email.split("@")[0]);
  await expect(page.getByTestId("person-row")).toHaveCount(1);
  await page.getByTestId("person-row").click();
  await expect(page).toHaveURL(/\/admin\/user\?id=\d+$/);

  await expect(page.getByTestId("viewing-banner")).toContainText("You are viewing another person's data.");
  await expect(page.getByTestId("person-name")).toHaveText(email);
  await expect(page.getByRole("region", { name: "Profile" })).toContainText("Information Science");
  await expect(page.getByRole("region", { name: "Profile" })).toContainText("Internships");
  await expect(page.getByTestId("person-application")).toHaveCount(4);
  await expect(page.getByTestId("person-application").first().getByTestId("timeline")).toBeVisible();
  await expect(page.getByTestId("person-saved").first()).toBeVisible();
  const review = page.getByTestId("person-review");
  await expect(review).toHaveCount(1);
  await expect(review).toContainText("Line one.\n<script>alert(1)</script>");
  expect(await review.locator("script").count()).toBe(0);

  // the page has its own address: a reload stays
  await page.reload();
  await expect(page.getByTestId("person-name")).toHaveText(email);
});

test("the uploaded resume can be downloaded; someone without one says so", async ({ page }) => {
  await signInDemo(page);
  await page.goto("/admin?tab=users");
  await page.getByTestId("people-search").fill("demo@umd.edu");
  await page.getByTestId("person-row").first().click();
  await expect(page.getByRole("region", { name: "Uploaded resume" })).toContainText("resume.pdf");
  const download = page.waitForEvent("download");
  await page.getByTestId("download-uploaded").click();
  expect((await download).suggestedFilename()).toBe("resume.pdf");

  // a fictional student who never uploaded one (ids from admin-users.json)
  await page.goto("/admin/user?id=201");
  await expect(page.getByRole("region", { name: "Uploaded resume" })).toContainText("No resume uploaded.");
  await expect(page.getByTestId("download-uploaded")).toHaveCount(0);

  // the API says 404 for the file: its words are shown
  await page.goto("/admin/user?id=200");
  await page.evaluate(() => localStorage.setItem("step1.mock.fail", "404 GET /admin/users/200/resume-file"));
  await page.getByTestId("download-uploaded").click();
  await expect(errorNote(page)).toBeVisible();
});

test("an unknown id says so", async ({ page }) => {
  await signInDemo(page);
  await page.goto("/admin/user?id=99999");
  await expect(page.getByRole("heading", { name: "No such person" })).toBeVisible();
  await page.goto("/admin/user");
  await expect(page.getByRole("heading", { name: "No such person" })).toBeVisible();
});

test("anyone else gets the not-found page for the list and for a person", async ({ page }) => {
  await signIn(page, freshEmail("nosy"), "register");
  await expect(page).toHaveURL(/\/onboarding$/);
  for (const path of ["/admin?tab=users", "/admin/user?id=1", "/admin/user?id=200"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: "Page not found" }), path).toBeVisible();
    await expect(page.getByTestId("viewing-banner")).toHaveCount(0);
  }
});

for (const scheme of ["light", "dark"] as const) {
  for (const width of [1280, 375]) {
    test(`Users and a person's page are accessible and fit (${scheme}, ${width}px)`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ colorScheme: scheme });
      await signInDemo(page);
      await page.goto("/admin?tab=users");
      await expect(page.getByTestId("person-row").first()).toBeVisible();
      await expectAccessible(page, "users");
      await expectNoHorizontalScroll(page);
      await page.goto("/admin/user?id=1");
      await expect(page.getByTestId("viewing-banner")).toBeVisible();
      await expect(page.getByTestId("person-application").first()).toBeVisible();
      await expectAccessible(page, "a person");
      await expectNoHorizontalScroll(page);
      expect(await page.locator("body").innerText()).not.toContain("—");
    });
  }
}
