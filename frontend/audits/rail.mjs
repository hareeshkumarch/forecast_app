import { chromium } from "@playwright/test";

const BASE = process.env.BASE ?? "http://localhost:3000";
const CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

const browser = await chromium.launch({ executablePath: CHROME });
const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });
await page.waitForTimeout(1000);

await page.screenshot({ path: "audits/out-rail-open.png", clip: { x: 0, y: 0, width: 320, height: 300 } });
await page.click("#app-navigation button[aria-controls='app-navigation']");
await page.waitForTimeout(500);
await page.screenshot({ path: "audits/out-rail-shut.png", clip: { x: 0, y: 0, width: 320, height: 300 } });

await browser.close();
