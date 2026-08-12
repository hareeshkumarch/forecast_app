import { chromium } from "@playwright/test";

const BASE = process.env.BASE ?? "http://localhost:3000";
const CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

const browser = await chromium.launch({ executablePath: CHROME });
const fail = [];
const note = (ok, label, detail = "") => {
  console.log(`  ${ok ? "ok  " : "FAIL"} ${label}${detail ? `  — ${detail}` : ""}`);
  if (!ok) fail.push(label);
};

const visible = (page) =>
  page.evaluate(() => {
    const button = document.querySelector('header button[aria-label="Open navigation"]');
    if (!button) return { present: false, shown: false };
    const box = button.getBoundingClientRect();
    return { present: true, shown: box.width > 0 && box.height > 0 };
  });

console.log("\ndesktop");
{
  const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
  await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });
  await page.waitForTimeout(900);

  const state = await visible(page);
  note(!state.shown, "the collapse symbol is hidden beside the wordmark", JSON.stringify(state));
  note(
    (await page.locator('header a[href="/"]').count()) === 1,
    "the wordmark still goes home",
  );
  note(
    (await page.evaluate(() => document.querySelector("#app-navigation")?.getBoundingClientRect().width ?? 0)) > 100,
    "the navigation rail is on screen, so nothing needs opening",
  );
  await page.screenshot({ path: "audits/out-dashboard-header.png", clip: { x: 0, y: 0, width: 620, height: 60 } });
  await page.close();
}

console.log("\nmobile");
{
  const page = await browser.newPage({ viewport: { width: 430, height: 900 }, hasTouch: true, isMobile: true });
  await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });
  await page.waitForTimeout(900);

  const state = await visible(page);
  note(state.shown, "the button is there, because the rail is not", JSON.stringify(state));

  // The mobile rail is a Radix dialog in a portal, not the inline #app-navigation.
  await page.click('header button[aria-label="Open navigation"]');
  await page.waitForTimeout(500);
  const opened = await page.evaluate(() => {
    const drawer = document.querySelector('[role="dialog"]');
    if (!drawer) return { width: 0, title: "none", links: 0 };
    return {
      width: Math.round(drawer.getBoundingClientRect().width),
      title: drawer.textContent?.trim().slice(0, 20) ?? "",
      links: drawer.querySelectorAll("a").length,
    };
  });
  note(opened.width > 100 && opened.links > 0, "tapping it opens the navigation", JSON.stringify(opened));
  await page.close();
}

console.log("\nthe chevron in the left rail");
{
  const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
  await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });
  await page.waitForTimeout(900);

  const read = () =>
    page.evaluate(() => {
      const rail = document.querySelector("#app-navigation");
      const button = rail?.querySelector("button[aria-controls='app-navigation']");
      if (!rail || !button) return null;
      const icon = button.querySelector("svg");
      const railBox = rail.getBoundingClientRect();
      const box = button.getBoundingClientRect();
      return {
        railWidth: Math.round(railBox.width),
        label: button.getAttribute("aria-label"),
        expanded: button.getAttribute("aria-expanded"),
        rotated: Math.round(new DOMMatrixReadOnly(getComputedStyle(icon).transform).a),
        offCentre: Math.round(box.x + box.width / 2 - (railBox.x + railBox.width / 2)),
      };
    });

  const open = await read();
  note(open !== null, "the rail carries its own collapse control", JSON.stringify(open));
  note(open?.label === "Collapse navigation", "it says what it does when open");
  note(open?.rotated === -1, "the chevron points back at the rail when open", `scaleX ${open?.rotated}`);

  await page.click("#app-navigation button[aria-controls='app-navigation']");
  await page.waitForTimeout(400);
  const shut = await read();
  note(shut?.railWidth !== undefined && shut.railWidth < 80, "clicking it collapses the rail", `${shut?.railWidth}px`);
  note(shut?.label === "Expand navigation", "it offers the way back");
  note(shut?.rotated === 1, "and the chevron flips to point out", `scaleX ${shut?.rotated}`);
  note(Math.abs(shut?.offCentre ?? 99) <= 1, "it sits centred in the collapsed strip", `${shut?.offCentre}px off`);

  await page.click("#app-navigation button[aria-controls='app-navigation']");
  await page.waitForTimeout(400);
  note((await read())?.railWidth === open?.railWidth, "and it reopens to where it was");
  await page.close();
}

console.log("\nthe mobile drawer has no collapse control");
{
  const page = await browser.newPage({ viewport: { width: 430, height: 900 }, hasTouch: true, isMobile: true });
  await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });
  await page.waitForTimeout(900);
  await page.click('header button[aria-label="Open navigation"]');
  await page.waitForTimeout(500);
  const inDrawer = await page.evaluate(
    () => document.querySelectorAll('[role="dialog"] button[aria-controls="app-navigation"]').length,
  );
  note(inDrawer === 0, "collapsing makes no sense in a drawer, so it is not offered", `${inDrawer} found`);
  await page.close();
}

console.log("\nkeyboard route is still there on desktop");
{
  const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
  await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });
  await page.waitForTimeout(900);
  const before = await page.evaluate(() => document.querySelector("#app-navigation")?.getBoundingClientRect().width ?? 0);
  await page.keyboard.press("[");
  await page.waitForTimeout(450);
  const after = await page.evaluate(() => document.querySelector("#app-navigation")?.getBoundingClientRect().width ?? 0);
  note(after < before, "the [ shortcut still collapses the rail", `${Math.round(before)} -> ${Math.round(after)}`);
  await page.close();
}

console.log(fail.length === 0 ? "\nHEADER GATE: PASS" : `\nHEADER GATE: ${fail.length} FAILURES`);
fail.forEach((f) => console.log(`  - ${f}`));
await browser.close();
process.exit(fail.length === 0 ? 0 : 1);
