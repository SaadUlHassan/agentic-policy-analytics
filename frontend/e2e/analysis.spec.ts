import { expect, type Page, test } from "@playwright/test";

// The offline stand-in answers like an agent; the data are the committed real-data snapshots.
const QUESTION = "Analyse employment trends in the technology sector from 2020-2024";

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "the page must not scroll sideways").toBeLessThanOrEqual(0);
}

async function ask(page: Page, question: string) {
  await page.goto("/");
  await page.getByRole("textbox", { name: "Research question" }).fill(question);
  await page.getByRole("button", { name: "Run analysis" }).click();
  await expect(page).toHaveURL(/\/analyses\/[0-9a-f-]{36}$/);
}

test("a question becomes a verified, cited report that can be explored and exported", async ({ page }) => {
  await ask(page, QUESTION);

  const findings = page.getByRole("region", { name: "Findings" });
  await expect(findings.getByRole("listitem")).toHaveCount(2);
  await expect(findings).toContainText("grew at a compound rate of");
  await expect(findings).toContainText("rose by");

  await expect(page.getByRole("region", { name: "Agent activity" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Research plan" })).toContainText("2020–2024");
  // Cited from two platforms: SingStat and Data.gov.sg.
  const sources = page.getByRole("region", { name: "Sources" });
  await expect(sources).toContainText("M182841");
  await expect(sources).toContainText("via SingStat");
  await expect(sources).toContainText("via Data.gov.sg");

  // The chart's table view shows the plotted source values.
  const charts = page.getByRole("region", { name: "Charts" });
  await charts.getByRole("button", { name: "Show table" }).first().click();
  await expect(charts.getByRole("table").first()).toContainText("2024");

  const exports = page.getByRole("navigation", { name: "Export" });
  for (const format of ["md", "json", "csv"]) {
    await expect(exports.locator(`a[href$="format=${format}"]`)).toBeVisible();
  }
  const markdown = await page.request.get(await exports.locator('a[href$="format=md"]').getAttribute("href") ?? "");
  expect(markdown.ok()).toBeTruthy();
  expect(await markdown.text()).toContain("compound rate");

  await noHorizontalScroll(page);

  // The analysis is in the history on the home page.
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Recent analyses" })).toContainText(QUESTION);
  await noHorizontalScroll(page);
});

test("an ambiguous question is asked about, and the answer resumes the analysis", async ({ page }) => {
  await ask(page, "How is the sector doing?");

  const question = page.getByRole("region", { name: "Question from the coordinator" });
  await expect(question).toContainText("Which sector do you mean?");
  await noHorizontalScroll(page);
  await question.getByRole("button", { name: "Information & Communications" }).click();

  await expect(page.getByRole("region", { name: "Findings" }).getByRole("listitem")).toHaveCount(2);
});

test("a question must be long enough before it can be run", async ({ page }) => {
  await page.goto("/");
  const run = page.getByRole("button", { name: "Run analysis" });
  await expect(run).toBeDisabled();
  await page.getByRole("textbox", { name: "Research question" }).fill("ab");
  await expect(run).toBeDisabled();
  await page.getByRole("textbox", { name: "Research question" }).fill("ICT employment");
  await expect(run).toBeEnabled();
  await noHorizontalScroll(page);
});
