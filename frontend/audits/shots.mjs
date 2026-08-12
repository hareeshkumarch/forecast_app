import { chromium } from "@playwright/test";

const BASE = process.env.BASE ?? "http://localhost:3000";
const CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

const browser = await chromium.launch({ executablePath: CHROME });

const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(BASE, { waitUntil: "networkidle" });
await page.waitForTimeout(2200);
await page.screenshot({ path: "audits/out-landing-full.png", fullPage: true });
await page.screenshot({ path: "audits/out-landing-fold.png" });

const sections = await page.evaluate(() =>
  [...document.querySelectorAll("section[id], header[id]")].map((el) => {
    const r = el.getBoundingClientRect();
    return {
      id: el.id,
      top: Math.round(r.top + window.scrollY),
      height: Math.round(r.height),
      heading: el.querySelector("h1,h2")?.textContent?.trim().slice(0, 60) ?? "",
    };
  }),
);
console.log(JSON.stringify(sections, null, 1));
await page.close();

const dash = await browser.newPage({ viewport: { width: 1600, height: 950 } });
await dash.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });
await dash.waitForTimeout(1400);
await dash.screenshot({ path: "audits/out-dashboard.png" });
await dash.screenshot({ path: "audits/out-dashboard-header.png", clip: { x: 0, y: 0, width: 620, height: 60 } });
await dash.close();

await browser.close();
