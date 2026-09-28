// The whole path a new student takes:
// login → onboarding → building → dashboard → save → apply → advance timeline.
import { expect, test } from "@playwright/test";
import status from "../src/lib/mock/status.json";
import transitions from "../src/lib/mock/transitions.json";
import { errorNote, freshEmail, pdfFile, signIn } from "./helpers";

const graph = transitions.graph as Record<string, string[]>;

test("new student: register through to advancing an application", async ({ page }) => {
  // ---- login ----
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/); // unauthenticated users are redirected
  await signIn(page, freshEmail("journey"), "register");
  await expect(page).toHaveURL(/\/onboarding$/);

  // ---- onboarding ----
  await expect(page.getByLabel("School")).toHaveValue("University of Maryland, College Park");
  await page.getByLabel("Major").fill("Information Science");
  const submit = page.getByTestId("submit-profile");
  const ranked = page.getByTestId("ranked-interest");

  await expect(submit).toBeDisabled(); // 0 interests
  await page.getByRole("button", { name: "+ Security" }).click();
  await page.getByRole("button", { name: "+ Software Engineering" }).click();
  await expect(ranked).toHaveCount(2);
  await expect(submit).toBeDisabled(); // 2 is too few
  await expect(page.getByTestId("interest-status")).toContainText("at least 3");

  await page.getByRole("button", { name: "+ AI / ML / Data Science" }).click();
  await expect(submit).toBeEnabled(); // 3 is fine
  await page.getByRole("button", { name: "+ Cloud, Infra & DevOps" }).click();
  await page.getByRole("button", { name: "+ Product Management" }).click();
  await expect(ranked).toHaveCount(5);
  await expect(submit).toBeEnabled(); // 5 is fine

  await page.getByRole("button", { name: "+ Research" }).click();
  await expect(ranked).toHaveCount(6);
  await expect(submit).toBeDisabled(); // 6 is too many
  await expect(page.getByTestId("interest-status")).toContainText("at most 5");
  await page.getByRole("button", { name: "Remove Research" }).click();
  await expect(submit).toBeEnabled();

  // rank is visible as 1..5 and reorderable
  await expect(ranked.nth(0)).toContainText("1");
  await expect(ranked.nth(0)).toContainText("Security");
  await expect(ranked.nth(1)).toContainText("2");
  await expect(ranked.nth(1)).toContainText("Software Engineering");
  await page.getByRole("button", { name: "Move Software Engineering up" }).click();
  await expect(ranked.nth(0)).toContainText("Software Engineering");
  await expect(ranked.nth(0).getByLabel("Rank 1")).toBeVisible();
  await expect(ranked.nth(1)).toContainText("Security");
  await expect(ranked.nth(4).getByLabel("Rank 5")).toBeVisible();

  // locations + resume
  await page.getByRole("textbox", { name: "Preferred locations" }).fill("Washington, DC");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.locator("#resume-file").setInputFiles({ ...pdfFile("notes.docx"), mimeType: "application/msword" });
  await expect(errorNote(page)).toContainText("must be a PDF");
  await page.locator("#resume-file").setInputFiles(pdfFile());
  const skills = page.getByRole("list", { name: "Extracted skills" });
  await expect(skills.getByText("Python")).toBeVisible();
  await page.getByRole("button", { name: "Remove skill Tableau" }).click();
  await expect(skills.getByText("Tableau")).toHaveCount(0);

  // ---- building ----
  await submit.click();
  await expect(page).toHaveURL(/\/onboarding\/building/);
  const step = page.getByTestId("building-step");
  const stepTexts = status.sequence.map((s) => s.step);
  await expect(step).toHaveText(new RegExp(stepTexts.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")));
  await expect(page.getByRole("progressbar")).toBeVisible();

  // ---- dashboard ----
  await expect(page).toHaveURL(/\/$/, { timeout: 15_000 });
  const cards = page.getByTestId("posting-card");
  await expect(cards.first()).toBeVisible();
  await expect(cards.first().getByRole("list", { name: "Why this matches" })).toBeVisible();

  // deleted skill persisted through PUT /profile
  await page.goto("/onboarding");
  await expect(page.getByRole("list", { name: "Extracted skills" }).getByText("Python")).toBeVisible();
  await expect(page.getByRole("list", { name: "Extracted skills" }).getByText("Tableau")).toHaveCount(0);
  await expect(page.getByTestId("ranked-interest").nth(0)).toContainText("Software Engineering");
  await page.goto("/");

  // ---- save ----
  const target = cards.filter({ has: page.getByTestId("apply-button") }).filter({
    has: page.getByRole("button", { name: "Save", exact: true }),
  }).first();
  const title = (await target.getByRole("heading").innerText()).trim();
  const postingId = await target.getAttribute("data-posting-id");
  const card = page.locator(`[data-posting-id="${postingId}"]`);
  await card.getByTestId("save-toggle").click();
  await expect(card.getByTestId("save-toggle")).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("link", { name: "Saved" }).click();
  await expect(page).toHaveURL(/\/saved$/);
  await expect(page.locator(`[data-posting-id="${postingId}"]`)).toBeVisible();

  // unsave removes it from the saved list…
  await page.locator(`[data-posting-id="${postingId}"]`).getByTestId("save-toggle").click();
  await expect(page.locator(`[data-posting-id="${postingId}"]`)).toHaveCount(0);
  // …and saving again from the dashboard brings it back
  await page.getByRole("link", { name: "Matches" }).click();
  await card.getByTestId("save-toggle").click();
  await expect(card.getByTestId("save-toggle")).toHaveAttribute("aria-pressed", "true");

  // ---- apply ----
  await card.getByTestId("apply-button").click();
  await page.getByTestId("confirm-applied").click();
  const appLink = card.getByTestId("application-link");
  await expect(appLink).toContainText("Applied");
  await appLink.click();

  // ---- timeline ----
  await expect(page).toHaveURL(/\/applications\/\d+$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
  const events = page.getByTestId("timeline-event");
  await expect(events).toHaveCount(1);
  await expect(events.first()).toHaveAttribute("data-kind", "applied");
  await expect(events.first()).toHaveAttribute("aria-current", "step");

  const buttons = page.getByTestId("transition-button");
  const kinds = async () => buttons.evaluateAll((els) => els.map((e) => e.getAttribute("data-kind")));
  expect(await kinds()).toEqual(graph.applied);

  // advance twice, each time picking from whatever the API offered
  let current = "applied";
  for (const pick of ["interview_scheduled", "interviewed"]) {
    expect(graph[current]).toContain(pick);
    await page.locator(`[data-testid="transition-button"][data-kind="${pick}"]`).click();
    await page.getByPlaceholder("Who you spoke to").fill(`note for ${pick}`);
    await page.getByTestId("save-event").click();
    await expect(page.getByTestId("status-pill").first()).toHaveAttribute("data-status", pick);
    await expect(page.locator(`[data-testid="timeline-event"][data-kind="${pick}"]`)).toHaveAttribute("aria-current", "step");
    await expect(page.getByTestId("timeline")).toContainText(`note for ${pick}`);
    await expect.poll(kinds).toEqual(graph[pick]);
    current = pick;
  }
  await expect(events).toHaveCount(3);

  // a note doesn't move the state
  await page.getByTestId("add-note").click();
  await page.getByPlaceholder("What do you want to remember?").fill("Send thank-you email");
  await page.getByTestId("save-event").click();
  await expect(events).toHaveCount(4);
  await expect(page.getByTestId("status-pill").first()).toHaveAttribute("data-status", "interviewed");
  expect(await kinds()).toEqual(graph.interviewed);

  // a terminal state leaves no buttons
  await page.locator('[data-testid="transition-button"][data-kind="rejected"]').click();
  await page.getByTestId("save-event").click();
  await expect(page.getByTestId("no-transitions")).toBeVisible();
  await expect(buttons).toHaveCount(0);

  // ---- applications list ----
  await page.getByRole("link", { name: "← All applications" }).click();
  const group = page.locator('[data-testid="status-group"][data-status="rejected"]');
  await expect(group.getByTestId("group-count")).toHaveText("2");
  await expect(group).toContainText(title);
});
