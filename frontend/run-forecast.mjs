import { chromium } from "@playwright/test";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 960 } });
const errs = [];
p.on("pageerror", e => errs.push("PAGEERROR: " + e.message));
await p.goto("http://localhost:3000", { waitUntil: "networkidle" });
await p.waitForTimeout(1500);

await p.getByRole("button", { name: /New Forecast/i }).click();
await p.waitForTimeout(600);
await p.getByRole("button", { name: /^Run Forecast$/ }).click();


const seen = [];
for (let i = 0; i < 90; i++) {
  await p.waitForTimeout(400);
  const txt = await p.locator('[role="progressbar"]').count()
    ? await p.locator('[role="dialog"]').innerText().catch(() => "")
    : "";
  const stage = (txt.split("\n")[2] || "").trim();
  if (stage && seen[seen.length - 1] !== stage) seen.push(stage);
  if (txt.includes("Forecast complete") || txt.includes("failed")) break;
}
console.log("SSE stages observed:");
seen.forEach(s => console.log("  -", s));
await p.screenshot({ path: "m-progress.png", clip: { x: 500, y: 240, width: 600, height: 460 } });
console.log("page errors:", errs.length ? errs : "none");
await b.close();
