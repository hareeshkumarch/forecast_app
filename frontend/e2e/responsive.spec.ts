import { expect, test, type Page } from "@playwright/test";

/**
 * The layout contract, per breakpoint:
 *
 *   < 1024   primary navigation is a drawer
 *   >= 1024  application navigation is inline
 *   >= 1720  the contextual insights rail joins it
 *
 * and at every width the page itself never scrolls sideways.
 */

const appNavigation = (page: Page) => page.locator('aside[aria-label="Primary navigation"]');
const insightsRail = (page: Page) => page.locator('aside[aria-label="Forecast insights"]');

async function load(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
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
  await expect(insightsRail(page)).toBeVisible({ visible: width >= 1720 });

  if (width < 1024) {
    await page.getByRole("button", { name: "Open navigation" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByRole("link", { name: /Dashboard/ })).toBeVisible();
    await page.keyboard.press("Escape");
  }

  if (width < 1720) {
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

  // A phone gets one chart per row; a workspace with room gets two.
  expect(columns.charts).toBe(width < 1024 ? 1 : 2);
  expect(columns.panels).toBe(width < 880 ? 1 : 2);

  if (columns.kpi > 0) {
    expect(columns.kpi).toBeGreaterThanOrEqual(width < 660 ? 2 : 3);
  }
});

test("the header keeps its controls reachable at every width", async ({ page }) => {
  await load(page);

  const width = page.viewportSize()?.width ?? 0;

  // Scenario, run and window collapse into one filters button on narrow screens.
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
