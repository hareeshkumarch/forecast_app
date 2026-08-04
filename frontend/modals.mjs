import { chromium } from "@playwright/test";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 960 } });
const errs = [];
p.on("pageerror", e => errs.push("PAGEERROR: " + e.message));
await p.goto("http://localhost:3000", { waitUntil: "networkidle" });
await p.waitForTimeout(2000);


await p.getByRole("button", { name: /Add Connector/i }).click();
await p.waitForTimeout(900);
await p.screenshot({ path: "m-connector.png", clip: { x: 460, y: 60, width: 680, height: 700 } });
await p.keyboard.press("Escape"); await p.waitForTimeout(400);


await p.getByRole("button", { name: /Upload Data/i }).click();
await p.waitForTimeout(700);
await p.screenshot({ path: "m-upload.png", clip: { x: 460, y: 240, width: 680, height: 420 } });
await p.keyboard.press("Escape"); await p.waitForTimeout(400);


await p.getByRole("button", { name: /New Forecast/i }).click();
await p.waitForTimeout(900);
await p.screenshot({ path: "m-forecast.png", clip: { x: 500, y: 130, width: 600, height: 640 } });
await p.keyboard.press("Escape"); await p.waitForTimeout(400);


await p.getByRole("button", { name: /View Details/i }).first().click();
await p.waitForTimeout(700);
await p.screenshot({ path: "m-drawer.png", clip: { x: 1180, y: 0, width: 420, height: 900 } });

console.log("page errors:", errs.length ? errs : "none");
await b.close();
