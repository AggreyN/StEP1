// What the profile form collects, the limits it states, and how uploads and
// rate limits are handled.
import { expect, test, type Page } from "@playwright/test";
import { PASSWORD, errorNote, freshEmail, pdfFile, signIn, signInDemo } from "./helpers";

type Sent = { line: string; body: Record<string, unknown> | null };

const sent = (page: Page, prefix: string): Promise<Sent[]> =>
  page.evaluate((p) => {
    const w = window as unknown as { __step1Requests?: string[]; __step1Bodies?: (Record<string, unknown> | null)[] };
    return (w.__step1Requests ?? [])
      .map((line, i) => ({ line, body: (w.__step1Bodies ?? [])[i] ?? null }))
      .filter((r) => r.line.startsWith(p));
  }, prefix);

async function newStudent(page: Page) {
  await signIn(page, freshEmail("onb"), "register");
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(page.getByLabel("Major")).toBeVisible();
}

test("GPA is not asked for and not sent", async ({ page }) => {
  await signInDemo(page); // the demo profile has a GPA on record
  await page.goto("/onboarding");
  await expect(page.getByLabel("Major")).toHaveValue("Information Science");
  await expect(page.getByLabel(/GPA/i)).toHaveCount(0);
  await expect(page.getByRole("main")).not.toContainText(/GPA/i);

  await page.getByTestId("submit-profile").click();
  await expect(page).toHaveURL(/\/onboarding\/building/);
  const puts = await sent(page, "PUT /profile");
  expect(puts.length).toBeGreaterThan(0);
  for (const put of puts) {
    expect(Object.keys(put.body!)).not.toContain("gpa");
    expect(Object.keys(put.body!).sort()).toEqual(
      [
        "degree_level",
        "grad_year",
        "interests",
        "looking_for",
        "major",
        "minor",
        "preferred_locations",
        "remote_ok",
        "school",
        "skills",
        "target_terms",
      ].sort()
    );
  }
});

test.describe("resume upload", () => {
  test.beforeEach(async ({ page }) => {
    await newStudent(page);
  });

  const uploads = (page: Page) => sent(page, "POST /profile/resume");

  test("a file under 1 KB is refused before any request", async ({ page }) => {
    await page.locator("#resume-file").setInputFiles(pdfFile("tiny.pdf", 300));
    await expect(errorNote(page)).toHaveText(
      "That file is only 300 bytes, which is too small to be a resume. It needs to be at least 1 KB."
    );
    expect(await uploads(page)).toEqual([]);
  });

  test("a file over 5 MB is refused before any request", async ({ page }) => {
    await page.locator("#resume-file").setInputFiles(pdfFile("huge.pdf", 5 * 1024 * 1024 + 1));
    await expect(errorNote(page)).toHaveText("That file is 5.0 MB. Resumes can be at most 5 MB.");
    expect(await uploads(page)).toEqual([]);
  });

  test("anything that isn't a PDF is refused before any request", async ({ page }) => {
    await page.locator("#resume-file").setInputFiles({ ...pdfFile("resume.docx"), mimeType: "application/msword" });
    await expect(errorNote(page)).toHaveText("Resumes must be PDF files. Export your resume as a PDF and try again.");
    // a PDF name on a file the browser knows is something else
    await page.locator("#resume-file").setInputFiles({ ...pdfFile("photo.pdf"), mimeType: "image/png" });
    await expect(errorNote(page)).toHaveText("Resumes must be PDF files. Export your resume as a PDF and try again.");
    expect(await uploads(page)).toEqual([]);
  });

  test("the limits themselves are accepted, and presign is told the size", async ({ page }) => {
    await page.locator("#resume-file").setInputFiles(pdfFile("smallest.pdf", 1024));
    await expect(page.getByRole("list", { name: "Extracted skills" })).toBeVisible();
    await page.locator("#resume-file").setInputFiles(pdfFile("largest.pdf", 5 * 1024 * 1024));
    await expect(page.getByText("largest.pdf")).toBeVisible();
    await expect(errorNote(page)).toHaveCount(0);

    const presigns = await sent(page, "POST /profile/resume/presign");
    expect(presigns.map((p) => p.body)).toEqual([
      { filename: "smallest.pdf", content_type: "application/pdf", size: 1024 },
      { filename: "largest.pdf", content_type: "application/pdf", size: 5 * 1024 * 1024 },
    ]);
  });

  test("the server's verdict on the contents is shown as it is", async ({ page }) => {
    await page.locator("#resume-file").setInputFiles(pdfFile("notpdf-renamed.pdf"));
    await expect(errorNote(page)).toHaveText("That file isn't a PDF.");
    await expect(page.getByRole("list", { name: "Extracted skills" })).toHaveCount(0);
    // and a good file afterwards still works
    await page.locator("#resume-file").setInputFiles(pdfFile());
    await expect(page.getByRole("list", { name: "Extracted skills" })).toBeVisible();
    await expect(errorNote(page)).toHaveCount(0);
  });
});

test.describe("limits are stated in the form", () => {
  test("school, major and minor stop at 120 characters", async ({ page }) => {
    await newStudent(page);
    for (const n of ["+ Security", "+ Software Engineering", "+ Research"]) {
      await page.getByRole("button", { name: n }).click();
    }
    await page.getByLabel("Major").fill("M".repeat(120));
    await expect(page.getByTestId("submit-profile")).toBeEnabled();

    await page.getByLabel("Major").fill("M".repeat(121));
    await expect(page.getByText("Major can be at most 120 characters (you have 121).").first()).toBeVisible();
    await expect(page.getByTestId("submit-profile")).toBeDisabled();
    await page.getByLabel("Major").fill("Information Science");

    await page.getByLabel("Minor").fill("m".repeat(130));
    await expect(page.getByText("Minor can be at most 120 characters (you have 130).").first()).toBeVisible();
    await expect(page.getByTestId("submit-profile")).toBeDisabled();
    await page.getByLabel("Minor").fill("");

    await page.getByLabel("School").fill("S".repeat(121));
    await expect(page.getByText("School can be at most 120 characters (you have 121).").first()).toBeVisible();
    await expect(page.getByTestId("submit-profile")).toBeDisabled();
    await page.getByLabel("School").fill("University of Maryland, College Park");
    await expect(page.getByTestId("submit-profile")).toBeEnabled();
  });

  test("preferred locations: 100 characters each, 20 at most", async ({ page }) => {
    await newStudent(page);
    const box = page.getByRole("textbox", { name: "Preferred locations" });
    const add = page.getByRole("button", { name: "Add", exact: true });

    await box.fill("x".repeat(101));
    await expect(page.getByText("Each one can be at most 100 characters (this is 101).")).toBeVisible();
    await expect(add).toBeDisabled();
    await box.press("Enter"); // the keyboard can't get round it either
    await expect(page.getByRole("list", { name: "Preferred locations" })).toHaveCount(0);

    await box.fill("x".repeat(100));
    await expect(add).toBeEnabled();
    await add.click();
    for (let i = 2; i <= 20; i++) {
      await box.fill(`City ${i}`);
      await box.press("Enter");
    }
    const chips = page.getByRole("list", { name: "Preferred locations" }).getByRole("listitem");
    await expect(chips).toHaveCount(20);
    await expect(page.getByText("That's the most you can add (20). Remove one to add another.")).toBeVisible();
    await box.fill("One too many");
    await expect(add).toBeDisabled();
    await box.press("Enter");
    await expect(chips).toHaveCount(20);

    await page.getByRole("button", { name: "Remove City 20" }).click();
    await expect(chips).toHaveCount(19);
    await expect(add).toBeEnabled();
  });

  test("a note stops at 2000 characters", async ({ page }) => {
    await signInDemo(page);
    await page.goto("/application?id=12");
    await page.getByTestId("add-note").click();
    const note = page.getByPlaceholder("What do you want to remember?");
    await note.fill("n".repeat(2000));
    await expect(page.getByText("2,000 of 2,000 characters")).toBeVisible();
    await expect(page.getByTestId("save-event")).toBeEnabled();
    await note.fill("n".repeat(2001));
    await expect(page.getByText("A note can be at most 2000 characters (you have 2001).")).toBeVisible();
    await expect(page.getByTestId("save-event")).toBeDisabled();
  });

  test("a display name stops at 80 characters", async ({ page }) => {
    await page.goto("/login");
    await page.getByRole("tab", { name: "Register" }).click();
    await page.getByLabel("Email").fill(freshEmail("name"));
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByLabel(/^Name/).fill("N".repeat(81));
    await expect(page.getByText("Name can be at most 80 characters (you have 81).")).toBeVisible();
    await expect(page.getByRole("button", { name: "Create account" })).toBeDisabled();
    await page.getByLabel(/^Name/).fill("N".repeat(80));
    await expect(page.getByRole("button", { name: "Create account" })).toBeEnabled();
  });

  test("if the server disagrees anyway, its message is shown", async ({ page }) => {
    await signInDemo(page);
    await page.goto("/onboarding");
    await expect(page.getByLabel("Major")).toHaveValue("Information Science");
    await page.evaluate(() => localStorage.setItem("step1.mock.fail", "422 PUT /profile"));
    await page.getByTestId("submit-profile").click();
    await expect(errorNote(page)).toContainText("The server had a problem.");
    await expect(page).toHaveURL(/\/onboarding$/);
  });
});

test.describe("rate limits (429)", () => {
  test("sign-in: shows the API's message, stays signed out, does not retry", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => localStorage.setItem("step1.mock.fail", "429 always POST /auth/login"));
    await page.getByLabel("Email").fill("demo@umd.edu");
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(errorNote(page)).toHaveText("Too many attempts. Wait a minute and try again.");
    await expect(page).toHaveURL(/\/login$/);
    expect(await page.evaluate(() => localStorage.getItem("step1.token"))).toBeNull();

    await page.waitForTimeout(1500);
    expect((await sent(page, "POST /auth/login")).length).toBe(1); // one attempt, no automatic retry
    // the form is usable again for a deliberate second try
    await expect(page.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  test("signed in: a 429 shows its message and keeps the session", async ({ page }) => {
    await signInDemo(page);
    await page.evaluate(() => localStorage.setItem("step1.mock.fail", "429 POST /saved"));
    const toggle = page.getByTestId("posting-card").first().getByTestId("save-toggle");
    const before = await toggle.getAttribute("aria-pressed");
    await toggle.click();
    await expect(errorNote(page)).toHaveText("Too many attempts. Wait a minute and try again.");
    await expect(toggle).toHaveAttribute("aria-pressed", before!); // rolled back
    await expect(page).toHaveURL(/\/$/);
    expect(await page.evaluate(() => localStorage.getItem("step1.token"))).not.toBeNull();
  });

  test("building: stops polling and waits to be asked", async ({ page }) => {
    await signInDemo(page);
    await page.evaluate(() => {
      localStorage.setItem("step1.mock.stuck", "1");
      localStorage.setItem("step1.mock.fail", "429 always GET /feed/status");
    });
    await page.goto("/onboarding/building?retry=1");
    await expect(errorNote(page)).toContainText("Too many attempts. Wait a minute and try again.");
    const polls = async () => (await sent(page, "GET /feed/status")).length;
    const after = await polls();
    await page.waitForTimeout(2500);
    expect(await polls()).toBe(after); // no polling behind the scenes

    await page.evaluate(() => localStorage.removeItem("step1.mock.fail"));
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByTestId("building-step")).toHaveText("Scanning 4,139 open internships");
    await expect(errorNote(page)).toHaveCount(0);
  });
});
