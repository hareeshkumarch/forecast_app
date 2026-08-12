import { chromium } from "@playwright/test";

const BASE = process.env.BASE ?? "http://localhost:3000";
const CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

const browser = await chromium.launch({ executablePath: CHROME });
const fail = [];
const note = (ok, label, detail = "") => {
  console.log(`  ${ok ? "ok  " : "FAIL"} ${label}${detail ? `  — ${detail}` : ""}`);
  if (!ok) fail.push(label);
};

console.log("\nthe wordmark goes home");
{
  const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
  await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });
  await page.waitForTimeout(800);
  const link = page.locator('header a[href="/"]');
  note((await link.count()) === 1, "the wordmark is a link to /");
  await link.click();
  await page.waitForURL(`${BASE}/`, { timeout: 5000 }).catch(() => undefined);
  note(new URL(page.url()).pathname === "/", "clicking it lands on the landing page", page.url());
  note(
    (await page.locator("#top h1").count()) === 1,
    "and the landing hero is what rendered",
  );
  await page.close();
}

console.log("\nthe rails collapse independently");
{
  const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
  await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });
  await page.waitForTimeout(900);

  const railWidth = () => page.evaluate(() => document.querySelector("#app-insights")?.getBoundingClientRect().width ?? -1);
  const navWidth = () => page.evaluate(() => document.querySelector("#app-navigation")?.getBoundingClientRect().width ?? -1);

  const openInsights = await railWidth();
  note(openInsights > 200, "the insights rail is present and open", `${openInsights}px`);

  await page.click('button[aria-label="Collapse forecast insights"]');
  await page.waitForTimeout(400);
  const shutInsights = await railWidth();
  note(shutInsights > 0 && shutInsights < 80, "it collapses to a strip", `${shutInsights}px`);
  note(
    (await page.locator('button[aria-label="Expand forecast insights"]').count()) === 1,
    "the strip offers a way back",
  );

  const navBefore = await navWidth();
  await page.click('button[aria-label="Expand forecast insights"]');
  await page.waitForTimeout(400);
  note((await railWidth()) > 200, "and it reopens");
  note((await navWidth()) === navBefore, "the navigation rail was untouched throughout");

  // Persistence across a reload.
  await page.click('button[aria-label="Collapse forecast insights"]');
  await page.waitForTimeout(300);
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(900);
  note((await railWidth()) < 80, "the choice survives a reload", `${await railWidth()}px`);
  await page.close();
}

console.log("\nmotion in the product");
{
  const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
  await page.goto(`${BASE}/dashboard`, { waitUntil: "domcontentloaded" });
  const animated = await page.evaluate(async () => {
    await new Promise((r) => setTimeout(r, 500));
    const named = new Set();
    for (const el of document.querySelectorAll("*")) {
      for (const a of el.getAnimations()) {
        const name = a.animationName ?? a.effect?.getKeyframes?.()?.length;
        if (a.animationName) named.add(a.animationName);
        void name;
      }
    }
    return [...named];
  });
  note(animated.length > 0, "something animates on arrival", animated.join(", ") || "nothing");

  const props = await page.evaluate(() => {
    const bad = [];
    for (const sheet of document.styleSheets) {
      let rules;
      try {
        rules = sheet.cssRules;
      } catch {
        continue;
      }
      for (const rule of rules) {
        if (rule.type !== CSSRule.KEYFRAMES_RULE) continue;
        if (!/^app-|^scape-|^grow-|^accuracy-/.test(rule.name)) continue;
        for (const frame of rule.cssRules) {
          for (const prop of frame.style) {
            if (["width", "height", "top", "left", "margin", "padding"].includes(prop))
              bad.push(`${rule.name}: ${prop}`);
          }
        }
      }
    }
    return bad;
  });
  note(props.length === 0, "no keyframe animates a layout property", props.join(", "));
  await page.close();
}

console.log("\nreduced motion in the product");
{
  const page = await browser.newPage({
    viewport: { width: 1600, height: 950 },
    reducedMotion: "reduce",
  });
  await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });
  await page.waitForTimeout(700);
  const r = await page.evaluate(() => {
    const faded = [...document.querySelectorAll(".stagger > *, .rise-in, .fade-in")].filter(
      (el) => +getComputedStyle(el).opacity < 0.99,
    ).length;
    return { faded, total: document.querySelectorAll(".stagger > *, .rise-in, .fade-in").length };
  });
  note(r.faded === 0, "everything is at full opacity on mount", `${r.faded}/${r.total} faded`);
  await page.close();
}

console.log(fail.length === 0 ? "\nPRODUCT GATE: PASS" : `\nPRODUCT GATE: ${fail.length} FAILURES`);
fail.forEach((f) => console.log(`  - ${f}`));
await browser.close();
process.exit(fail.length === 0 ? 0 : 1);
