import { expect, test, type Page } from "@playwright/test";

const appNavigation = (page: Page) => page.locator('aside[aria-label="Primary navigation"]');
const insightsRail = (page: Page) => page.locator('aside[aria-label="Forecast insights"]');

async function load(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  await expect(page.locator('[data-workspace]:not([data-workspace="loading"])')).toBeVisible({
    timeout: 15_000,
  });
}

test("the page never scrolls horizontally", async ({ page }) => {
  await load(page);

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));

  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
});

test("rails are inline or drawers according to the viewport", async ({ page }, testInfo) => {
  await load(page);

  const width = page.viewportSize()?.width ?? 0;
  await expect(appNavigation(page)).toBeVisible({ visible: width >= 1024 });
  await expect(insightsRail(page)).toBeVisible({ visible: width >= 1440 });

  if (width < 1024) {
    await page.getByRole("button", { name: "Open navigation" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByRole("link", { name: /Dashboard/ })).toBeVisible();
    await page.keyboard.press("Escape");
  }

  if (width < 1440) {
    await page.getByRole("button", { name: /Forecast insights/ }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
  }

  testInfo.annotations.push({ type: "viewport", description: String(width) });
});

test("panels reflow to the width the workspace actually has", async ({ page }) => {
  await load(page);

  const width = page.viewportSize()?.width ?? 0;
  const columns = await page.evaluate(() => {
    const count = (selector: string) => {
      const element = document.querySelector(selector);
      if (!element) return 0;
      return getComputedStyle(element).gridTemplateColumns.split(" ").filter(Boolean).length;
    };
    return { kpi: count(".grid-kpi"), charts: count(".grid-charts"), panels: count(".grid-panels") };
  });

  expect(columns.charts).toBe(width < 1024 ? 1 : 2);
  expect(columns.panels).toBe(width < 880 ? 1 : 2);

  if (columns.kpi > 0) {
    expect(columns.kpi).toBeGreaterThanOrEqual(width < 660 ? 2 : 3);
  }
});

test("the header keeps its controls reachable at every width", async ({ page }) => {
  await load(page);

  const width = page.viewportSize()?.width ?? 0;

  if (width < 768) {
    await expect(page.getByRole("button", { name: "Filters" })).toBeVisible();
    await page.getByRole("button", { name: "Filters" }).click();
    await expect(page.getByText("Forecast window")).toBeVisible();
    await page.keyboard.press("Escape");
  } else {
    await expect(page.getByRole("button", { name: /Base Case/ })).toBeVisible();
  }

  await expect(page.getByRole("button", { name: "Export" })).toBeVisible();
});

test("the logo collapses the rail on desktop and opens the sheet below it", async ({ page }) => {
  await load(page);

  const width = page.viewportSize()?.width ?? 0;
  const rail = appNavigation(page);
  const railWidth = async () => (await rail.boundingBox())?.width ?? 0;

  if (width < 1024) {
    await page.getByRole("button", { name: "Open navigation" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    return;
  }

  expect(await railWidth()).toBeGreaterThan(160);

  await page.getByRole("button", { name: "Collapse navigation" }).click();
  await expect(rail).toHaveAttribute("data-collapsed", "");

  await expect.poll(railWidth, { timeout: 3000 }).toBeLessThan(90);

  await expect(page.getByRole("link", { name: "Connectors" })).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(rail).toHaveAttribute("data-collapsed", "", { timeout: 5000 });

  await page.getByRole("button", { name: "Expand navigation" }).click();
  await expect(rail).not.toHaveAttribute("data-collapsed", "");
  await expect.poll(railWidth, { timeout: 3000 }).toBeGreaterThan(160);
});

test("a rich selector shows why to pick each option and commits the choice", async ({ page }) => {
  await load(page);

  await page.getByRole("button", { name: /new forecast/i }).first().click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  const frequency = dialog.getByRole("combobox").nth(1);
  await expect(frequency).toHaveText(/Monthly/);

  await frequency.click();
  const listbox = page.getByRole("listbox");
  await expect(listbox).toBeVisible();

  const quarterly = listbox.getByRole("option", { name: /Quarterly/ });
  await expect(quarterly).toContainText("One point per quarter");

  await quarterly.click();
  await expect(listbox).toBeHidden();
  await expect(frequency).toHaveText(/Quarterly/);

  await page.keyboard.press("Escape");
});
