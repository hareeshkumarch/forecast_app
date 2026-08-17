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

test("the primary call to action opens the dashboard", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("link", { name: "Open the dashboard" }).first().click();
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
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  for (const heading of [
    "From a spreadsheet to a plan in three steps.",
    "Everything a planner needs, and nothing they do not.",
    "A range tells you more than a perfect-looking line.",
    // The accuracy figure counts up the first time it is scrolled to, so this
    // heading's name is whatever the count is currently showing. Matching the
    // finished sentence would deadlock: the count does not start until the
    // heading is in view, and the heading cannot be scrolled to until it
    // matches. The words either side of the number are what is stable.
    /of the sales it had never seen/,
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

/*
 * The landing page was light by construction, and the one element that read
 * the theme tokens while the rest did not gave a visitor on a dark OS two
 * near-black smudges behind a light headline. These three cover the shape of
 * that bug from both ends: the whole page has to move together, and it has to
 * move for the OS as well as for the button.
 */
test("the landing page follows the operating system's colour scheme", async ({ browser }) => {
  const context = await browser.newContext({ colorScheme: "dark" });
  const page = await context.newPage();
  await page.goto("/");

  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  const canvas = await page
    .locator(".forecast-landing")
    .evaluate((node) => getComputedStyle(node).backgroundColor);
  expect(canvas).toBe("rgb(17, 21, 18)");

  await context.close();
});

test("the theme control switches the page and is remembered", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  const inkOf = (selector: string) =>
    page.locator(selector).first().evaluate((node) => getComputedStyle(node).backgroundColor);

  const litPage = await inkOf(".forecast-landing");
  // The chart is drawn in SVG with its own palette, which is exactly where a
  // half-themed page shows: the frame flips and the drawing inside does not.
  const litChart = await page
    .locator('.scape-bar[data-tone="history"][data-row="0"] polygon')
    .first()
    .evaluate((node) => getComputedStyle(node).fill);

  await page.getByRole("button", { name: "Switch between light and dark" }).click();

  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await inkOf(".forecast-landing")).not.toBe(litPage);
  expect(
    await page
      .locator('.scape-bar[data-tone="history"][data-row="0"] polygon')
      .first()
      .evaluate((node) => getComputedStyle(node).fill),
  ).not.toBe(litChart);

  // Survives a reload, and without a flash: the bootstrap script in the
  // document head sets the theme before anything paints, so the very first
  // frame is already dark.
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("the choice made on the landing page is the one the dashboard opens in", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Switch between light and dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  await page.goto("/dashboard");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("the nav call to action fits its pill on the narrowest phones", async ({ page }) => {
  // The full label wrapped to two lines and spilled out of a fixed-height pill
  // below roughly 360px, which is where the older Android widths sit.
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/");

  const cta = page.getByRole("navigation", { name: "Sections" }).getByRole("link", {
    name: "Open the dashboard",
  });

  // The pill is collapsed to nothing until the hero has been scrolled past —
  // it is the nav's copy of a call to action the hero is still showing. There
  // is no pill to measure before that.
  await expect(cta).toBeHidden();
  await page.evaluate(() => window.scrollTo(0, 900));
  await expect(cta).toBeVisible();

  const fits = await cta.evaluate((node) => node.scrollHeight <= node.clientHeight);
  expect(fits).toBe(true);
});

test("the section nav only appears once it has room for one line", async ({ page }) => {
  await page.goto("/");

  const nav = page.getByRole("navigation", { name: "Sections" });
  if (!(await nav.isVisible())) return;

  // Below the large breakpoint the list is display:none and there is nothing
  // to measure — which is the "only appears once it has room" the name means.
  for (const link of await nav.locator("[data-section]:visible").all()) {
    const box = await link.boundingBox();
    expect(box, "every section link has a box").not.toBeNull();

    // Measured against the link's own line-height rather than a fixed pixel
    // count. The type scale here is fluid, so a single line is a different
    // number of pixels at every width — a constant threshold only ever
    // described one of them, and grew stale the moment the scale changed.
    const onOneLine = await link.evaluate((node) => {
      const styles = getComputedStyle(node);
      const box = node.getBoundingClientRect();
      const frame =
        parseFloat(styles.paddingTop) +
        parseFloat(styles.paddingBottom) +
        parseFloat(styles.borderTopWidth) +
        parseFloat(styles.borderBottomWidth);
      // A second line adds a whole line-height, so half of one is a margin no
      // single-line box can cross and no wrapped box can stay under.
      return box.height - frame <= parseFloat(styles.lineHeight) * 1.5;
    });
    expect(onOneLine, "every section link sits on one line").toBe(true);
  }
});
