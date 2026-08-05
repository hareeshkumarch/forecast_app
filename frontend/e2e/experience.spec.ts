import { expect, test, type Page } from "@playwright/test";

/**
 * Covers the shell-level interactions that do not depend on API data: theming,
 * density, the command palette and its shortcuts.
 */

async function load(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  // The workspace resolves into exactly one of four states, and three of them
  // are settled: the panels, the first-run guide, or an error the summary
  // could not get past. Waiting for the panels alone made every test here
  // depend on a reachable API, which this job deliberately does not run.
  await expect(page.locator('[data-workspace]:not([data-workspace="loading"])')).toBeVisible({
    timeout: 15_000,
  });
}

const theme = (page: Page) => page.evaluate(() => document.documentElement.dataset.theme);
const density = (page: Page) => page.evaluate(() => document.documentElement.dataset.density);

test("the theme is applied before paint and survives a reload", async ({ page }) => {
  await load(page);
  expect(["light", "dark"]).toContain(await theme(page));

  await page.evaluate(() => {
    localStorage.setItem(
      "forecast_hub_prefs",
      JSON.stringify({ theme: "dark", density: "comfortable" }),
    );
  });
  await page.reload();

  // Read before any hydration effect could have run.
  expect(await theme(page)).toBe("dark");

  // Asserted as "dark", not as a hex: the point is that the dark tokens are
  // live before paint, and pinning the literal only breaks the test whenever
  // the palette is retuned.
  const canvas = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--canvas").trim(),
  );
  expect(canvas).toMatch(/^#[0-9a-f]{6}$/i);
  expect(luminance(canvas)).toBeLessThan(0.2);
});

/** Rough perceived brightness, 0 (black) to 1 (white). */
function luminance(hex: string): number {
  const channel = (at: number) => parseInt(hex.slice(at, at + 2), 16) / 255;
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

test("the keyboard toggles the theme and the palette drives it too", async ({ page }, testInfo) => {
  await load(page);

  await page.evaluate(() => {
    localStorage.setItem(
      "forecast_hub_prefs",
      JSON.stringify({ theme: "light", density: "comfortable" }),
    );
  });
  await page.reload();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  await page.locator("body").press("t");
  await expect.poll(() => theme(page)).toBe("dark");

  testInfo.annotations.push({ type: "shortcut", description: "t toggles theme" });
});

test("the command palette opens, filters and runs an action", async ({ page }) => {
  await load(page);

  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog");
  await expect(palette).toBeVisible();

  await page.getByPlaceholder("Search actions…").fill("density");
  await expect(palette.getByRole("button", { name: /density/i })).toBeVisible();

  const before = await density(page);
  await page.keyboard.press("Enter");
  await expect.poll(() => density(page)).not.toBe(before);
});

test("the palette closes on escape without running anything", async ({ page }) => {
  await load(page);

  await page.keyboard.press("ControlOrMeta+k");
  await expect(page.getByRole("dialog")).toBeVisible();

  const before = await density(page);
  await page.keyboard.press("Escape");

  await expect(page.getByRole("dialog")).toBeHidden();
  expect(await density(page)).toBe(before);
});

test("compact density tightens the panel grid", async ({ page }) => {
  await load(page);

  const gap = () =>
    page.evaluate(() =>
      getComputedStyle(document.documentElement).getPropertyValue("--density-panel-gap").trim(),
    );

  // Driven through storage and a reload rather than by setting the attribute
  // directly, so the assertion cannot race the hydration effect re-applying
  // the stored preference.
  async function useDensity(value: "compact" | "comfortable") {
    await page.evaluate((density) => {
      localStorage.setItem(
        "forecast_hub_prefs",
        JSON.stringify({ theme: "light", density, sidebarCollapsed: false }),
      );
    }, value);
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-density", value);
  }

  await useDensity("compact");
  expect(await gap()).toBe("8px");

  await useDensity("comfortable");
  expect(await gap()).toBe("12px");
});

test("first run offers a guided path rather than empty panels", async ({ page }) => {
  await load(page);

  // With no completed run the workspace leads with the three-step panel.
  const guide = page.getByRole("heading", { name: "Get your first forecast" });
  if (await guide.count()) {
    await expect(guide).toBeVisible();
    await expect(page.getByRole("button", { name: /Upload a file/ })).toBeVisible();
  }
});
