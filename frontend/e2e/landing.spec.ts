import { expect, test } from "@playwright/test";

/*
 * The landing page is the first thing anyone sees, and the one page that is
 * fully static — so what matters is that it composes at every width and that
 * its scroll animation is an enhancement rather than a prerequisite for
 * reading it.
 */

test("the landing page is the root and the app has moved to /dashboard", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1 })).toContainText("See your demand");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeHidden();
});

test("the primary call to action opens sign in", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("link", { name: "Start forecasting" }).first().click();
  await expect(page).toHaveURL(/\/signin$/);
});

test("the live workspace remains available as a demo", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("link", { name: "Open the dashboard" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
});

test("it never scrolls sideways, at any width", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));

  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
});

test("every section is readable once scrolled to", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  for (const heading of [
    "From a spreadsheet to a plan in three steps.",
    "Everything a planner needs, and nothing they do not.",
    "Know what changed, why it matters, and what to do next.",
    "A range tells you more than a perfect-looking line.",
    /Right about .* of the sales it had never seen\./,
    "See what is coming next.",
  ]) {
    const target = page.getByRole("heading", { name: heading });
    await target.scrollIntoViewIfNeeded();
    await expect(target).toBeVisible();
    // Revealed, not merely present: a stuck observer would leave it at zero.
    await expect
      .poll(() => target.evaluate((node) => Number(getComputedStyle(node).opacity)), {
        timeout: 4000,
      })
      .toBeGreaterThan(0.9);
  }
});

test("with reduced motion the page is composed from the first paint", async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: "reduce" });
  const page = await context.newPage();

  await page.goto("/");

  // No `.motion-ready`, so nothing was ever hidden and nothing has to animate
  // back into view.
  await expect(page.locator(".motion-ready")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Everything a planner needs, and nothing they do not." }),
  ).toBeVisible();

  await context.close();
});

test("the primary call to action fits on the narrowest phones", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/");

  const cta = page.getByRole("link", { name: "Start forecasting" }).first();
  await expect(cta).toBeVisible();

  const fits = await cta.evaluate((node) => node.scrollHeight <= node.clientHeight);
  expect(fits).toBe(true);
});

test("the section nav only appears once it has room for one line", async ({ page }) => {
  await page.goto("/");

  const nav = page.getByRole("navigation", { name: "Sections" });
  const sectionLinks = nav.locator("ul").first().getByRole("link");
  if (!(await sectionLinks.first().isVisible())) return;

  for (const link of await sectionLinks.all()) {
    const box = await link.boundingBox();
    expect(box, "every section link has a box").not.toBeNull();
    const textLines = await link.evaluate((node) => {
      const range = document.createRange();
      range.selectNodeContents(node);
      return range.getClientRects().length;
    });
    expect(textLines).toBe(1);
  }
});
