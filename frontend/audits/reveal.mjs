import { chromium } from "@playwright/test";

const BASE = process.env.BASE ?? "http://localhost:3000";
const CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

const browser = await chromium.launch({ executablePath: CHROME });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(BASE, { waitUntil: "networkidle" });
await page.waitForTimeout(1200);

const ids = ["how-it-works", "features", "compare", "accuracy"];

for (const id of ids) {
  await page.evaluate((target) => {
    document.getElementById(target)?.scrollIntoView({ block: "start", behavior: "instant" });
  }, id);
  await page.waitForTimeout(1400);

  const state = await page.evaluate((target) => {
    const section = document.getElementById(target);
    if (!section) return { id: target, missing: true };
    const reveals = [...section.querySelectorAll(".reveal, .rise-in, .fade-in")];
    const hidden = reveals.filter((el) => +getComputedStyle(el).opacity < 0.99);
    return {
      id: target,
      reveals: reveals.length,
      hidden: hidden.length,
      firstHidden: hidden[0]?.textContent?.trim().slice(0, 40) ?? "",
      sectionOpacity: +getComputedStyle(section).opacity,
    };
  }, id);
  console.log(JSON.stringify(state));
  await page.screenshot({ path: `audits/out-${id}.png` });
}

await browser.close();
