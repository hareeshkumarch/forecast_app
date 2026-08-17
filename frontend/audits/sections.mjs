import { chromium } from "@playwright/test";

const BASE = process.env.BASE ?? "http://localhost:3000";
const CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

const browser = await chromium.launch({ executablePath: CHROME });
const fail = [];
const line = (s) => console.log(s);

/*
 * Pointing at a forecast bar is not the same as taking the centre of its box.
 * The prisms are an isometric projection and overlap, so a box centre often
 * belongs to the bar in front; and the chart sits far enough down the hero to
 * run past the fold at ordinary window heights, where a point simply hovers
 * nothing. Scroll it in, then take the first bar that both hit-tests to itself
 * and lands on screen. Call it once the bars have stopped growing — a box
 * measured mid-build is the height the bar had, not the height it will have.
 */
const aimAtForecast = async (page) => {
  await page.evaluate(() =>
    document.querySelector("svg[role=img]").scrollIntoView({ block: "center" }),
  );
  const target = await page.evaluate(() => {
    const future = [
      ...document.querySelectorAll('svg[role=img] .scape-bar[data-tone="future"]'),
    ];
    for (const bar of [...future].reverse()) {
      const r = bar.getBoundingClientRect();
      const x = r.x + r.width / 2;
      const y = r.y + r.height * 0.7;
      if (x < 0 || x > innerWidth || y < 0 || y > innerHeight) continue;
      const hit = document.elementFromPoint(x, y);
      if (hit && bar.contains(hit)) return { x, y };
    }
    return null;
  });
  if (!target) throw new Error("no forecast bar was reachable by the pointer");
  return target;
};

/* ------------------------------------------------ 1: comparison wipes */
line("\n1 — the comparison panels draw themselves");
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.evaluate(() => document.querySelector("#compare").scrollIntoView());

  const wipes = await page.evaluate(async () => {
    const rects = [...document.querySelectorAll("#compare .draw-wipe")];
    // Sample the scaleX of every wipe rect across the sequence.
    const track = rects.map(() => []);
    const started = performance.now();
    await new Promise((resolve) => {
      const tick = () => {
        rects.forEach((r, i) => {
          const m = new DOMMatrixReadOnly(getComputedStyle(r).transform);
          track[i].push(m.a);
        });
        if (performance.now() - started < 1600) requestAnimationFrame(tick);
        else resolve();
      };
      requestAnimationFrame(tick);
    });
    return {
      count: rects.length,
      min: track.map((t) => Math.min(...t)),
      max: track.map((t) => Math.max(...t)),
      final: track.map((t) => t.at(-1)),
    };
  });

  const grew = wipes.min.every((v) => v < 0.05);
  const landed = wipes.final.every((v) => v > 0.999);
  const noOvershoot = wipes.max.every((v) => v <= 1.0001);
  if (wipes.count !== 4) fail.push(`1 expected 4 wipe rects, found ${wipes.count}`);
  if (!grew) fail.push(`1 a wipe never started from zero: ${JSON.stringify(wipes.min)}`);
  if (!landed) fail.push(`1 a wipe never reached full: ${JSON.stringify(wipes.final)}`);
  if (!noOvershoot) fail.push(`1 a wipe overshot: ${JSON.stringify(wipes.max)}`);
  line(`  ${wipes.count} wipes, min ${wipes.min.map((v) => v.toFixed(2))}, max ${wipes.max.map((v) => v.toFixed(3))}`);
  line(`  starts at zero ${grew ? "ok" : "FAIL"} · lands full ${landed ? "ok" : "FAIL"} · no overshoot ${noOvershoot ? "ok" : "FAIL"}`);
  await page.close();
}

/* ------------------------------------------------ 2: comparison budget */
line("\n2 — comparison and accuracy settle inside budget");
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(BASE, { waitUntil: "networkidle" });

  for (const [id, sel, budget] of [
    ["#compare", "#compare .draw-wipe, #compare .outcome-dot, #compare .outcome-ring", 1400],
    ["#accuracy", "#accuracy .accuracy-bar, #accuracy .check-ghost, #accuracy .grow-x", 1600],
  ]) {
    await page.evaluate((s) => document.querySelector(s).scrollIntoView(), id);
    await page.waitForTimeout(60);
    const settled = await page.evaluate((s) => {
      let end = 0;
      let n = 0;
      for (const el of document.querySelectorAll(s)) {
        for (const anim of el.getAnimations()) {
          const t = anim.effect.getTiming();
          end = Math.max(end, (t.delay ?? 0) + (t.duration ?? 0));
          n++;
        }
      }
      return { end, n };
    }, sel);

    const ok = settled.end > 0 && settled.end < budget;
    if (!ok) fail.push(`2 ${id} settles at ${settled.end}ms against a ${budget}ms budget`);
    line(`  ${id}: ${settled.n} animated marks, settles at ${settled.end}ms (budget ${budget}ms)  ${ok ? "ok" : "FAIL"}`);
  }
  await page.close();
}

/* ------------------------------------------------ 3: bars never overshoot */
line("\n3 — accuracy bars never pass their value");
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.evaluate(() => document.querySelector("#accuracy").scrollIntoView());

  const peak = await page.evaluate(async () => {
    const bars = [...document.querySelectorAll("#accuracy .accuracy-bar")];
    let worst = 0;
    const started = performance.now();
    await new Promise((resolve) => {
      const tick = () => {
        for (const bar of bars) {
          const m = new DOMMatrixReadOnly(getComputedStyle(bar).transform);
          worst = Math.max(worst, m.d);
        }
        if (performance.now() - started < 1800) requestAnimationFrame(tick);
        else resolve();
      };
      requestAnimationFrame(tick);
    });
    return { worst, bars: bars.length };
  });

  const ok = peak.worst <= 1.0001;
  if (!ok) fail.push(`3 a bar reached scaleY ${peak.worst}`);
  line(`  ${peak.bars} bars, peak scaleY ${peak.worst.toFixed(4)}  ${ok ? "ok" : "FAIL"}`);
  await page.close();
}

/* ------------------------------------------------ 4: the three beats land in order */
line("\n4 — the accuracy rows arrive in their stated order");
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.evaluate(() => document.querySelector("#accuracy").scrollIntoView());
  await page.waitForTimeout(60);

  const order = await page.evaluate(() => {
    const rows = [...document.querySelectorAll("#accuracy .accuracy-bar")].map((el) => {
      const anim = el.getAnimations()[0];
      return anim ? anim.effect.getTiming().delay : null;
    });
    const ghosts = [...document.querySelectorAll("#accuracy .check-ghost")].map(
      (el) => el.getAnimations()[0]?.effect.getTiming().delay ?? null,
    );
    const ticks = [...document.querySelectorAll("#accuracy .grow-x")].map(
      (el) => el.getAnimations()[0]?.effect.getTiming().delay ?? null,
    );
    return { firstBar: Math.min(...rows), lastBar: Math.max(...rows), ghosts, ticks };
  });

  const ghostsAfterStart = Math.min(...order.ghosts) > order.firstBar;
  const ticksLast = Math.min(...order.ticks) > Math.min(...order.ghosts);
  if (!ghostsAfterStart) fail.push("4 the hidden weeks did not wait behind the shown ones");
  if (!ticksLast) fail.push("4 the outcome rules did not arrive after the hidden weeks");
  line(`  bars ${order.firstBar}–${order.lastBar}ms · ghosts from ${Math.min(...order.ghosts)}ms · ticks from ${Math.min(...order.ticks)}ms`);
  line(`  held weeks wait ${ghostsAfterStart ? "ok" : "FAIL"} · outcome last ${ticksLast ? "ok" : "FAIL"}`);
  await page.close();
}

/* ------------------------------------------------ 5: count-up */
line("\n5 — the accuracy figure counts up without moving the sentence");
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(BASE, { waitUntil: "networkidle" });

  // While counting the number is a reserved box plus an overlay, so the
  // wrapper's own textContent is the placeholder and the value together. The
  // live figure is the last child when there is one.
  await page.addScriptTag({
    content: `window.__figure = () => {
      const el = document.querySelector("#accuracy [data-count-up]");
      return (el.lastElementChild ?? el).textContent.trim();
    };`,
  });
  const before = await page.evaluate(() => window.__figure());

  await page.evaluate(() => document.querySelector("#accuracy").scrollIntoView());
  const samples = await page.evaluate(async () => {
    const el = document.querySelector("#accuracy [data-count-up]");
    const seen = new Set();
    const widths = new Set();
    const started = performance.now();
    await new Promise((resolve) => {
      const tick = () => {
        seen.add(window.__figure());
        widths.add(Math.round(el.getBoundingClientRect().width * 10));
        if (performance.now() - started < 1400) requestAnimationFrame(tick);
        else resolve();
      };
      requestAnimationFrame(tick);
    });
    return { values: [...seen], widths: [...widths], final: window.__figure() };
  });

  const counted = samples.values.length > 8;
  const steady = samples.widths.length === 1;
  const landed = samples.final === "94";
  if (!counted) fail.push(`5 only saw ${samples.values.length} distinct values`);
  if (!steady) fail.push(`5 the number's box changed width: ${samples.widths}`);
  if (!landed) fail.push(`5 the count finished on "${samples.final}"`);
  line(`  armed at "${before}" · ${samples.values.length} distinct values · lands on "${samples.final}"`);
  line(`  counts ${counted ? "ok" : "FAIL"} · box holds one width ${steady ? "ok" : "FAIL"} · lands on 94 ${landed ? "ok" : "FAIL"}`);
  await page.close();
}

/* ------------------------------------------------ 6: reduced motion */
line("\n6 — reduced motion gets the finished page, not a blank one");
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.evaluate(() => document.querySelector("#accuracy").scrollIntoView());
  await page.waitForTimeout(200);

  const state = await page.evaluate(() => {
    const opaque = (sel) =>
      [...document.querySelectorAll(sel)].every((el) => Number(getComputedStyle(el).opacity) > 0.9);
    const full = (sel) =>
      [...document.querySelectorAll(sel)].every((el) => {
        const m = new DOMMatrixReadOnly(getComputedStyle(el).transform);
        return m.a > 0.99 && m.d > 0.99;
      });
    return {
      motionReady: document.querySelector(".forecast-landing").classList.contains("motion-ready"),
      wipesFull: full("#compare .draw-wipe"),
      barsFull: full("#accuracy .accuracy-bar"),
      ticksFull: full("#accuracy .grow-x"),
      dotsVisible: opaque("#compare .outcome-dot"),
      ghostsVisible: opaque("#accuracy .check-ghost"),
      figure: document.querySelector("#accuracy [data-count-up]")?.textContent.trim(),
    };
  });

  const ok =
    !state.motionReady &&
    state.wipesFull &&
    state.barsFull &&
    state.ticksFull &&
    state.dotsVisible &&
    state.ghostsVisible &&
    state.figure === "94";
  if (!ok) fail.push(`6 reduced motion left something hidden: ${JSON.stringify(state)}`);
  line(`  ${JSON.stringify(state)}`);
  line(`  everything rendered at rest  ${ok ? "ok" : "FAIL"}`);
  await page.close();
}

/* ------------------------------------------------ 7: no JavaScript */
line("\n7 — no JavaScript gets the finished page too");
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, javaScriptEnabled: false });
  await page.goto(BASE, { waitUntil: "load" });

  // `page.evaluate` needs the very thing that is switched off here, so every
  // measurement below is taken from outside the page.
  const figure = await page.locator("#accuracy h2").innerText();
  const wipes = await page.locator("#compare .draw-wipe").count();
  const bars = await page.locator("#accuracy .accuracy-bar").count();
  const shot = await page.locator("#compare").screenshot();

  const ok = figure.includes("94%") && wipes === 4 && bars > 0 && shot.length > 3000;
  if (!ok) fail.push(`7 no-JS render was incomplete: "${figure}", ${wipes} wipes, ${bars} bars`);
  line(`  heading "${figure.replace(/\s+/g, " ").trim()}"`);
  line(`  ${wipes} wipe rects, ${bars} bars, compare section paints  ${ok ? "ok" : "FAIL"}`);
  await page.close();
}

/* ------------------------------------------------ 8: hero untouched */
line("\n8 — the hero sequence is unchanged");
{
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.evaluate(() => document.querySelector('svg[role="img"]').scrollIntoView());
  await page.waitForTimeout(60);

  const seq = await page.evaluate(() => {
    const svg = document.querySelector('svg[role="img"]');
    let settled = 0;
    for (const el of svg.querySelectorAll(".scape-bar, .scape-caption")) {
      for (const anim of el.getAnimations()) {
        const t = anim.effect.getTiming();
        settled = Math.max(settled, (t.delay ?? 0) + (t.duration ?? 0));
      }
    }
    return settled;
  });

  const ok = seq > 0 && seq < 1400;
  if (!ok) fail.push(`8 hero sequence settles at ${seq}ms`);
  line(`  settles at ${seq}ms (budget 1400ms)  ${ok ? "ok" : "FAIL"}`);
  await page.close();
}

/* ------------------------------------------------ 9: the hero demonstrates itself */
line("\n9 — the hero walks its own forecast, once, and hands it back");
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(BASE, { waitUntil: "networkidle" });

  // Never touch the chart: this is what a visitor who only reads sees.
  const seen = await page.evaluate(async () => {
    const el = document.querySelector("p.scape-readout");
    const frames = [];
    const started = performance.now();
    await new Promise((resolve) => {
      const tick = () => {
        frames.push(el.innerText.trim());
        if (performance.now() - started < 5200) requestAnimationFrame(tick);
        else resolve();
      };
      requestAnimationFrame(tick);
    });
    return { distinct: [...new Set(frames)], last: frames.at(-1) };
  });

  const weeks = seen.distinct.filter((t) => /^Week \+\d/.test(t));
  const walked = weeks.length >= 5;
  const onlyForecast = !seen.distinct.some((t) => /weeks ago/.test(t));
  const handedBack = /Hover any week/i.test(seen.last);
  if (!walked) fail.push(`9 the demo showed ${weeks.length} forecast weeks`);
  if (!onlyForecast) fail.push("9 the demo walked history, which reads out as 'actual'");
  if (!handedBack) fail.push(`9 the demo did not restore the hint, ended on "${seen.last}"`);
  line(`  ${weeks.length} forecast weeks shown · ends on "${seen.last}"`);
  line(`  walks ${walked ? "ok" : "FAIL"} · forecast only ${onlyForecast ? "ok" : "FAIL"} · hint returns ${handedBack ? "ok" : "FAIL"}`);
  await page.close();
}

line("\n10 — touching the chart takes it from the demo for good");
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(BASE, { waitUntil: "networkidle" });

  // Aim once the build has stopped moving, then interrupt the walk in progress.
  await page.waitForTimeout(1500);
  const target = await aimAtForecast(page);
  await page.waitForTimeout(700);

  // Which week ends up under the cursor is not worth asserting — the prisms
  // are an isometric projection and overlap, so the bar the pointer lands on
  // may well be in front of the one aimed at. What matters is that the walk
  // stops: held still for four steps' worth of time, the readout must not
  // advance.
  await page.mouse.move(target.x, target.y);
  const held = await page.evaluate(async () => {
    const el = document.querySelector("p.scape-readout");
    const frames = [];
    const started = performance.now();
    await new Promise((resolve) => {
      const tick = () => {
        frames.push(el.innerText.trim());
        if (performance.now() - started < 900) requestAnimationFrame(tick);
        else resolve();
      };
      requestAnimationFrame(tick);
    });
    return [...new Set(frames)];
  });

  await page.mouse.move(10, 10);
  await page.waitForTimeout(1600);
  const after = await page.locator("p.scape-readout").innerText();

  const stopped = held.length === 1 && /^Week \+\d/.test(held[0]);
  const stayed = /Hover any week/i.test(after);
  if (!stopped) fail.push(`10 the walk did not stop under a still pointer: ${JSON.stringify(held)}`);
  if (!stayed) fail.push(`10 the demo resumed after being taken: "${after.trim()}"`);
  line(`  held still for 900ms: ${JSON.stringify(held)}`);
  line(`  1.6s after leaving: "${after.trim()}"`);
  line(`  walk stops ${stopped ? "ok" : "FAIL"} · demo stays off ${stayed ? "ok" : "FAIL"}`);
  await page.close();
}

line("\n11 — the demo is off under reduced motion, and the band still reads");
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForTimeout(4600);
  const readout = await page.locator("p.scape-readout").innerText();
  const band = await page.evaluate(() =>
    [...document.querySelectorAll("#top dl dt")].map((el) => el.innerText.replace(/\s+/g, "")),
  );

  const quiet = /Hover any week/i.test(readout);
  const complete = band.length === 4 && band.every((t) => /\d/.test(t));
  if (!quiet) fail.push(`11 the demo ran under reduced motion: "${readout.trim()}"`);
  if (!complete) fail.push(`11 the proof band did not render its figures: ${JSON.stringify(band)}`);
  line(`  readout "${readout.trim()}" · band ${JSON.stringify(band)}`);
  line(`  demo off ${quiet ? "ok" : "FAIL"} · band complete ${complete ? "ok" : "FAIL"}`);
  await page.close();
}

line("\n12 — the depth of the chart is two product lines, told apart");
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForTimeout(4600);

  // The rows overlap by design, so two rows painted the same colour read as
  // one silhouette and the third dimension says nothing. Compare the ink
  // actually rendered rather than the palette that was meant to be used.
  const rows = await page.evaluate(() => {
    const fills = (row) =>
      new Set(
        [...document.querySelectorAll(`.scape-frame .scape-bar[data-row="${row}"]:not(.scape-shell)`)]
          .flatMap((bar) => [...bar.querySelectorAll("polygon")])
          .map((face) => getComputedStyle(face).fill),
      );
    return {
      front: [...fills(0)],
      behind: [...fills(1)],
      names: [...document.querySelectorAll(".scape-frame svg text")].map((t) => t.textContent),
    };
  });

  const shared = rows.front.filter((fill) => rows.behind.includes(fill));
  const told = rows.front.length > 0 && rows.behind.length > 0 && shared.length === 0;
  // Both rows are named on the chart itself: a row a visitor cannot name is a
  // shape, not a product line.
  const named = ["Chilled", "Ambient"].every((name) => rows.names.includes(name));

  if (!told) fail.push(`12 the rows share ${shared.length} fills: ${JSON.stringify(shared)}`);
  if (!named) fail.push(`12 the rows are not named on the chart: ${JSON.stringify(rows.names)}`);
  line(`  front ${JSON.stringify(rows.front)}`);
  line(`  behind ${JSON.stringify(rows.behind)}`);
  line(`  rows told apart ${told ? "ok" : "FAIL"} · rows named ${named ? "ok" : "FAIL"}`);
  await page.close();
}

line("\n13 — a week reads out as a total and the lines that make it up");
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(BASE, { waitUntil: "networkidle" });

  // Take the chart mid-walk: pointing at it is the visitor taking over.
  await page.waitForTimeout(2100);
  const target = await aimAtForecast(page);
  await page.mouse.move(target.x, target.y);
  await page.waitForTimeout(200);
  const hovered = (await page.locator("p.scape-readout").innerText()).trim();

  const [headline = "", split = ""] = hovered.split("\n").map((part) => part.trim());
  const reads = /^Week \+\d+ · \d+ units\s+· range \d+ to \d+$/.test(headline);
  const parts = [...split.matchAll(/([A-Za-z]+) (\d+)/g)];
  const total = Number(headline.match(/· (\d+) units/)?.[1] ?? NaN);
  const summed = parts.reduce((sum, [, , value]) => sum + Number(value), 0);
  const addsUp = parts.length === 2 && summed === total;

  if (!reads) fail.push(`13 the readout did not report the week: "${headline}"`);
  if (!addsUp) fail.push(`13 "${split}" does not add up to ${total}`);
  line(`  headline "${headline}"`);
  line(`  split "${split}" -> ${summed}`);
  line(`  reads out ${reads ? "ok" : "FAIL"} · lines add up ${addsUp ? "ok" : "FAIL"}`);
  await page.close();
}

await browser.close();

line("");
if (fail.length) {
  line(`${fail.length} FAILURE(S):`);
  for (const f of fail) line(`  · ${f}`);
  process.exit(1);
}
line("all checks passed");
