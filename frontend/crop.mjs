import { chromium } from "@playwright/test";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 960 } });
await p.goto("http://localhost:3000", { waitUntil: "networkidle" });
await p.waitForTimeout(2500);
await p.screenshot({ path: "crop-chart.png", clip: { x: 240, y: 300, width: 530, height: 320 } });
await p.screenshot({ path: "crop-rail.png", clip: { x: 0, y: 80, width: 230, height: 400 } });
await b.close();
