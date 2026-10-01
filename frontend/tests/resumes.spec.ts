// Tailored resumes: the base resume, tailoring for a posting or pasted text,
// saving, downloading, renaming and deleting.
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

/** The demo student has an uploaded resume; build and save their base. */
async function setUpBase(page: Page) {
  await page.goto("/resume");
  await page.getByTestId("extract-base").click();
  await expect(page.getByTestId("resume-editor")).toBeVisible();
  await page.getByTestId("save-base").click();
  await expect(page.getByTestId("base-status")).toHaveText("Saved.");
}

test.describe("the base resume", () => {
  test("built from the upload, edited, saved, and still there after a reload", async ({ page }) => {
    await signInDemo(page);
    await page.goto("/resume");
    await expect(page.getByTestId("base-empty")).toContainText("You don't have a base resume yet");
    await expect(page.getByRole("main")).toContainText("Every tailored resume is built from this one.");
    await page.getByTestId("extract-base").click();

    const editor = page.getByTestId("resume-editor");
    await expect(editor.getByLabel("Name", { exact: true })).toHaveValue("Jordan Ellis");
    await expect(page.getByTestId("resume-section")).toHaveCount(4);
    await expect(page.getByTestId("base-status")).toHaveText("Unsaved changes.");

    // edit the name, a heading, and the bullets of the first job
    await editor.getByLabel("Name", { exact: true }).fill("Jordan A. Ellis");
    const experience = page.getByRole("region", { name: "Experience" });
    const first = "Experience entry 1";
    await expect(experience.getByRole("textbox", { name: `${first} heading`, exact: true })).toHaveValue("Terrapin Tutoring Center");
    const bullets = experience.getByTestId("resume-entry").first().getByTestId("resume-line");
    await expect(bullets).toHaveCount(2);
    await experience.getByRole("button", { name: "Add bullet" }).first().click();
    await expect(bullets).toHaveCount(3);
    await experience.getByRole("textbox", { name: `${first} bullet 3`, exact: true }).fill("Ran weekly review sessions before every midterm");
    await experience.getByRole("button", { name: `Move ${first} bullet 3 up` }).click();
    await expect(experience.getByRole("textbox", { name: `${first} bullet 2`, exact: true })).toHaveValue("Ran weekly review sessions before every midterm");
    await experience.getByRole("button", { name: `Remove ${first} bullet 1` }).click();
    await expect(bullets).toHaveCount(2);
    await expect(experience.getByRole("textbox", { name: `${first} bullet 1`, exact: true })).toHaveValue("Ran weekly review sessions before every midterm");

    // a very long bullet gets a hint, not a refusal
    await experience.getByRole("textbox", { name: `${first} bullet 2`, exact: true }).fill("x".repeat(230));
    await expect(experience.getByText("230 of about 220 characters. Long for one line; consider trimming.")).toBeVisible();
    await experience.getByRole("textbox", { name: `${first} bullet 2`, exact: true }).fill("Wrote a practice problem bank of 60 exercises");

    // move a whole section, add one, and add a skill
    await page.getByRole("button", { name: "Move section Projects up" }).click();
    await expect(page.getByTestId("resume-section").nth(1)).toHaveAttribute("aria-label", "Projects");
    await page.getByRole("button", { name: "Add section" }).click();
    await expect(page.getByTestId("resume-section")).toHaveCount(5);
    await page.getByRole("textbox", { name: "Section 5 title", exact: true }).fill("Awards");
    await page.getByRole("textbox", { name: "Awards entry 1 heading", exact: true }).fill("Dean's List");
    const skills = page.getByRole("textbox", { name: "Skill list", exact: true });
    await skills.fill("Docker");
    await skills.press("Enter");
    await expect(page.getByRole("list", { name: "Skill list" })).toContainText("Docker");

    await page.getByTestId("save-base").click();
    await expect(page.getByTestId("base-status")).toHaveText("Saved.");
    const put = await page.evaluate(() => {
      const w = window as unknown as { __step1Requests?: string[]; __step1Bodies?: Record<string, unknown>[] };
      return (w.__step1Bodies ?? [])[(w.__step1Requests ?? []).lastIndexOf("PUT /resume/base")];
    });
    expect(put?.name).toBe("Jordan A. Ellis");
    expect(put?.skill_inventory).toContain("Docker");

    await page.reload();
    await expect(page.getByTestId("resume-editor").getByLabel("Name", { exact: true })).toHaveValue("Jordan A. Ellis");
    await expect(page.getByRole("region", { name: "Awards" })).toBeVisible();
    await expect(page.getByTestId("resume-section").nth(1)).toHaveAttribute("aria-label", "Projects");
  });

  test("with nothing uploaded, it points to Profile; the API's 409 is shown as it is", async ({ page }) => {
    await signIn(page, freshEmail("noresume"), "register");
    await page.getByLabel("Major").fill("Information Science");
    for (const n of ["+ Security", "+ Software Engineering", "+ Research"]) {
      await page.getByRole("button", { name: n }).click();
    }
    await page.getByTestId("submit-profile").click();
    await expect(page).toHaveURL(/\/$/, { timeout: 15_000 });
    await page.goto("/resume");
    await expect(page.getByTestId("needs-upload")).toContainText("First upload your resume on your Profile");
    await expect(page.getByTestId("needs-upload").getByRole("link", { name: "Profile" })).toHaveAttribute("href", "/onboarding");
    await expect(page.getByTestId("extract-base")).toHaveCount(0);

    await signInDemo(page);
    await page.goto("/resume");
    await page.evaluate(() => localStorage.setItem("step1.mock.fail", "409 POST /resume/base/extract"));
    await page.getByTestId("extract-base").click();
    await expect(errorNote(page)).toHaveText("Upload your resume first.");
  });

  test("bullets can be moved with the keyboard alone", async ({ page }) => {
    await signInDemo(page);
    await page.goto("/resume");
    await page.getByTestId("extract-base").click();
    const up = page.getByRole("button", { name: "Move Experience entry 1 bullet 2 up" });
    await up.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("textbox", { name: "Experience entry 1 bullet 1", exact: true })).toHaveValue(/^Wrote a practice problem bank/);
    // at the top it can't go further, but keeps focus
    const nowFirstUp = page.getByRole("button", { name: "Move Experience entry 1 bullet 1 up" });
    await nowFirstUp.focus();
    await expect(nowFirstUp).toHaveAttribute("aria-disabled", "true");
    await page.keyboard.press("Enter");
    await expect(nowFirstUp).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Move Experience entry 1 bullet 1 down" })).toBeFocused();
  });
});

test.describe("tailoring", () => {
  test("for a posting: from the card, edited, named, saved, listed and downloaded", async ({ page }) => {
    await signInDemo(page);
    await setUpBase(page);
    await page.goto("/");
    const card = page.getByTestId("posting-card").first();
    const title = (await card.getByRole("heading").innerText()).trim();
    const company = (await card.locator("p").first().locator("span").first().innerText()).trim();
    await card.getByTestId("tailor-button").click();
    await expect(page).toHaveURL(/\/tailor\?posting=/);

    const progress = page.getByTestId("tailoring");
    await expect(progress).toContainText(`Tailoring your resume for ${title} at ${company}`);
    await expect(progress).toContainText("can take up to a minute");
    await expect(progress).not.toContainText("%");

    const report = page.getByTestId("tailor-report");
    await expect(report).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId("report-fit")).toContainText("A good fit.");
    await expect(page.getByTestId("report-changes").getByRole("listitem")).toHaveCount(3);
    await expect(page.getByTestId("report-gaps").getByRole("listitem")).toHaveCount(2);
    await expect(page.getByTestId("report-question")).toContainText("Have you used AWS, Azure or GCP");

    // the draft: Projects moved up, editable; the name is suggested
    await expect(page.getByTestId("resume-section").nth(1)).toHaveAttribute("aria-label", "Projects");
    await expect(page.getByTestId("resume-name")).toHaveValue(`${company}, ${title}`.slice(0, 80));
    await expect(page.getByTestId("tailored-status")).toHaveText("Not saved yet.");
    await page.getByRole("textbox", { name: "Projects entry 1 bullet 1", exact: true }).fill("Built a live shuttle map used by about 300 students a day");
    await page.getByTestId("resume-name").fill("Shuttle-first version");
    await page.getByTestId("save-tailored").click();
    await expect(page.getByTestId("tailored-status")).toContainText("Saved.");

    // in Saved resumes, for the right job
    await page.getByTestId("tailored-status").getByRole("link", { name: "Saved resumes" }).click();
    await expect(page).toHaveURL(/\/resumes$/);
    const saved = page.getByTestId("saved-resume");
    await expect(saved).toHaveCount(1);
    await expect(saved).toContainText("Shuttle-first version");
    await expect(saved).toContainText(`For ${title} at ${company}`);

    // both downloads, under the server's file names
    for (const [format, ext] of [
      ["pdf", "pdf"],
      ["docx", "docx"],
    ] as const) {
      const download = page.waitForEvent("download");
      await saved.getByTestId(`download-${format}`).click();
      expect((await download).suggestedFilename()).toBe(`Jordan_Ellis_Shuttle_first_version.${ext}`);
    }

    // open it: the edit survived
    await saved.getByRole("link", { name: "Open Shuttle-first version" }).click();
    await expect(page).toHaveURL(/\/resumes\/edit\?id=\d+$/);
    await expect(page.getByRole("textbox", { name: "Projects entry 1 bullet 1", exact: true })).toHaveValue("Built a live shuttle map used by about 300 students a day");
    await page.reload();
    await expect(page.getByTestId("resume-name")).toHaveValue("Shuttle-first version");
  });

  test("for pasted text; downloading before saving saves first", async ({ page }) => {
    await signInDemo(page);
    await setUpBase(page);
    await page.goto("/tailor");
    const box = page.getByTestId("job-text");
    await expect(page.getByTestId("tailor-text")).toBeDisabled();
    await box.fill("x".repeat(20001));
    await expect(page.getByText("20,001 of 20,000 characters. That is 1 too many.")).toBeVisible();
    await expect(page.getByTestId("tailor-text")).toBeDisabled();
    await box.fill("Data Analyst Intern. SQL, Python, Tableau. Present findings to managers.");
    await page.getByTestId("tailor-text").click();
    await expect(page.getByTestId("tailoring")).toContainText("Tailoring your resume for the job you pasted");
    await expect(page.getByTestId("report-fit")).toContainText("A reasonable fit", { timeout: 10_000 });
    await expect(page.getByTestId("report-question")).toHaveCount(0);
    await expect(page.getByTestId("resume-name")).toHaveValue("Tailored resume");

    const posted = () =>
      page.evaluate(() => ((window as unknown as { __step1Requests?: string[] }).__step1Requests ?? []).filter((r) => r === "POST /resumes"));
    expect(await posted()).toHaveLength(0);
    const download = page.waitForEvent("download");
    await page.getByTestId("download-pdf").click();
    expect((await download).suggestedFilename()).toBe("Jordan_Ellis_Tailored_resume.pdf");
    expect(await posted()).toHaveLength(1); // saved once, first
    await expect(page.getByTestId("tailored-status")).toContainText("Saved.");
    // a second download uses the saved copy
    const again = page.waitForEvent("download");
    await page.getByTestId("download-docx").click();
    expect((await again).suggestedFilename()).toBe("Jordan_Ellis_Tailored_resume.docx");
    expect(await posted()).toHaveLength(1);

    await page.goto("/resumes");
    await expect(page.getByTestId("saved-resume")).toContainText("For a pasted job description");
  });

  test("without a base resume: the API's 409 and a link to set one up", async ({ page }) => {
    await signInDemo(page);
    await page.goto("/tailor");
    await page.getByTestId("job-text").fill("Software intern");
    await page.getByTestId("tailor-text").click();
    await expect(errorNote(page)).toHaveText("Set up your base resume first.", { timeout: 10_000 });
    await page.getByTestId("tailor-problem").getByRole("link", { name: "Set up your base resume" }).click();
    await expect(page).toHaveURL(/\/resume$/);
  });

  test("too many today (429) and a busy writer (503) show the API's words and can be retried", async ({ page }) => {
    await signInDemo(page);
    await setUpBase(page);
    await page.evaluate(() => localStorage.setItem("step1.mock.fail", "429 POST /tailor"));
    await page.goto(`/tailor?posting=${encodeURIComponent("simplify:9a5e7e29-0251-947b-cc3b-3121ae79507c")}`);
    await expect(errorNote(page)).toHaveText("You've tailored a lot of resumes today. Try again tomorrow.", { timeout: 10_000 });
    await page.evaluate(() => localStorage.setItem("step1.mock.fail", "503 POST /tailor"));
    await page.getByTestId("tailor-again").click();
    await expect(errorNote(page)).toHaveText("The resume writer is busy right now. Try again in a few minutes.", { timeout: 10_000 });
    await page.getByTestId("tailor-again").click();
    await expect(page.getByTestId("tailor-report")).toBeVisible({ timeout: 10_000 });
  });

  test("the timeline has a Tailor resume button too", async ({ page }) => {
    await signInDemo(page);
    await page.goto("/application?id=12");
    await page.getByTestId("tailor-button").click();
    await expect(page).toHaveURL(/\/tailor\?posting=/);
  });
});

test("saved resumes: rename inline and delete with a confirm", async ({ page }) => {
  await signInDemo(page);
  await setUpBase(page);
  await page.goto("/tailor");
  await page.getByTestId("job-text").fill("Business analyst internship");
  await page.getByTestId("tailor-text").click();
  await expect(page.getByTestId("tailor-report")).toBeVisible({ timeout: 10_000 });
  await page.getByTestId("save-tailored").click();
  await expect(page.getByTestId("tailored-status")).toContainText("Saved.");

  await page.goto("/resumes");
  const saved = page.getByTestId("saved-resume");
  await saved.getByTestId("rename").click();
  const input = page.getByTestId("rename-input");
  await expect(input).toBeFocused();
  await input.fill("");
  await expect(page.getByTestId("rename-save")).toBeDisabled();
  await input.fill("BA internship version");
  await input.press("Enter");
  await expect(page.getByTestId("saved-resume-name")).toHaveText("BA internship version");
  await page.reload();
  await expect(page.getByTestId("saved-resume-name")).toHaveText("BA internship version");

  await saved.getByTestId("delete-resume").click();
  const dialog = page.getByRole("dialog", { name: "Delete this resume?" });
  await expect(dialog).toContainText("BA internship version will be deleted for good.");
  await dialog.getByRole("button", { name: "Keep it" }).click();
  await expect(saved).toHaveCount(1);
  await saved.getByTestId("delete-resume").click();
  await dialog.getByTestId("confirm-delete-resume").click();
  await expect(page.getByTestId("resumes-empty")).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("resumes-empty")).toBeVisible();
});

test("five tabs fit on a phone, and Resumes is one of them", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signInDemo(page);
  const tabs = page.getByRole("navigation", { name: "Main" }).last().getByRole("link");
  await expect(tabs).toHaveText(["Matches", "Saved", "Applications", "Resumes", "Profile"]);
  const clipped = await tabs.evaluateAll((els) => els.filter((e) => e.scrollWidth > e.clientWidth).map((e) => e.textContent));
  expect(clipped).toEqual([]);
  await tabs.nth(3).click();
  await expect(page).toHaveURL(/\/resumes$/);
  await page.goto("/tailor");
  await expect(tabs.nth(3)).toHaveAttribute("aria-current", "page");
  await expectNoHorizontalScroll(page);
});

for (const scheme of ["light", "dark"] as const) {
  for (const width of [1280, 375]) {
    test(`resume screens are accessible and fit (${scheme}, ${width}px)`, async ({ page }) => {
      test.setTimeout(90_000);
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ colorScheme: scheme });
      await signInDemo(page);

      await page.goto("/resume");
      await expect(page.getByTestId("base-empty")).toBeVisible();
      await expectAccessible(page, "base resume, empty");
      await page.getByTestId("extract-base").click();
      await expect(page.getByTestId("resume-editor")).toBeVisible();
      await page.getByRole("textbox", { name: "Experience entry 1 bullet 1", exact: true }).fill("x".repeat(230));
      await expectAccessible(page, "base resume editor");
      await expectNoHorizontalScroll(page);
      await page.getByRole("textbox", { name: "Experience entry 1 bullet 1", exact: true }).fill("Tutor students");
      await page.getByTestId("save-base").click();
      await expect(page.getByTestId("base-status")).toHaveText("Saved.");

      await page.goto("/tailor");
      await expect(page.getByTestId("job-text")).toBeVisible();
      await expectAccessible(page, "tailor, form");
      await page.goto(`/tailor?posting=${encodeURIComponent("simplify:9a5e7e29-0251-947b-cc3b-3121ae79507c")}`);
      await expect(page.getByTestId("tailoring")).toBeVisible();
      await expectAccessible(page, "tailor, running");
      await expect(page.getByTestId("tailor-report")).toBeVisible({ timeout: 10_000 });
      await expectAccessible(page, "tailor, result");
      await expectNoHorizontalScroll(page);
      await page.getByTestId("save-tailored").click();
      await expect(page.getByTestId("tailored-status")).toContainText("Saved.");

      await page.goto("/resumes");
      await expect(page.getByTestId("saved-resume")).toHaveCount(1);
      await expectAccessible(page, "saved resumes");
      await expectNoHorizontalScroll(page);
      await page.getByTestId("delete-resume").click();
      await expect(page.getByRole("dialog")).toBeVisible();
      await expectAccessible(page, "delete dialog");
      await page.getByRole("button", { name: "Keep it" }).click();

      await page.getByRole("link", { name: /^Open / }).click();
      await expect(page.getByTestId("resume-editor")).toBeVisible();
      await expectAccessible(page, "saved resume, open");
      await expectNoHorizontalScroll(page);
      expect(await page.locator("body").innerText()).not.toContain("—");
    });
  }
}
