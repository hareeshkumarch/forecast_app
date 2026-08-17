import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/*
 * The trap this closes.
 *
 * Tailwind builds `bg-surface/95` by substituting an alpha into the colour the
 * config gave it. It can do that to a hex, and it cannot do it to a bare
 * `var(--surface)` — there is nowhere to put the number. Handed one, it does
 * not warn, does not fall back to the solid colour, and does not emit the rule
 * at all: the class lands in the markup, matches nothing, and the element
 * renders fully transparent.
 *
 * That failure is invisible in review and nearly invisible on screen. A
 * translucent nav over a light page still looks like a translucent nav; the
 * dashboard header carried it for months. It only announces itself when the
 * element passes over something dark.
 *
 * So the rule is: a token may be used at a fraction only if the config exposes
 * it as channels with an `<alpha-value>` slot. This test reads both sides —
 * every fractional use in the source, and every alpha-capable token in the
 * config — and fails on any use the config cannot actually build.
 */

const ROOT = join(__dirname, "..");
const SOURCE_DIRS = ["app", "components", "hooks", "lib", "stores"];

function sourceFiles(dir: string): string[] {
  const here = join(ROOT, dir);
  const found: string[] = [];
  for (const entry of readdirSync(here)) {
    const path = join(here, entry);
    if (statSync(path).isDirectory()) {
      found.push(...sourceFiles(join(dir, entry)));
    } else if (/\.tsx?$/.test(entry)) {
      found.push(path);
    }
  }
  return found;
}

/** Colour keys the Tailwind config declares, and which of them take an alpha. */
function configuredColours(): { all: Set<string>; alphaCapable: Set<string> } {
  const config = readFileSync(join(ROOT, "tailwind.config.ts"), "utf8");
  const colours = config.slice(config.indexOf("colors: {"), config.indexOf("borderRadius:"));

  const all = new Set<string>();
  const alphaCapable = new Set<string>();
  for (const [, quoted, bare, value] of colours.matchAll(
    /(?:"([\w-]+)"|([\w-]+))\s*:\s*"([^"]+)"/g,
  )) {
    const name = quoted ?? bare;
    if (!name) continue;
    all.add(name);
    if (value?.includes("<alpha-value>")) alphaCapable.add(name);
  }
  return { all, alphaCapable };
}

/** Every `bg-surface/95`-shaped use of a configured colour, with where it is. */
function fractionalUses(names: Set<string>): { token: string; where: string }[] {
  const prefixes = "bg|text|border|fill|stroke|from|via|to|ring|shadow|decoration|outline|divide|placeholder|caret|accent";
  const pattern = new RegExp(`\\b(?:${prefixes})-([\\w-]+)\\/\\d+`, "g");

  const uses: { token: string; where: string }[] = [];
  for (const dir of SOURCE_DIRS) {
    for (const file of sourceFiles(dir)) {
      const text = readFileSync(file, "utf8");
      for (const [, token] of text.matchAll(pattern)) {
        // `border-white/10` and friends are Tailwind's own palette, which is
        // written as channels already. Only our tokens are at risk.
        if (token && names.has(token)) {
          uses.push({ token, where: file.slice(ROOT.length + 1) });
        }
      }
    }
  }
  return uses;
}

describe("colour tokens used at a fraction of their strength", () => {
  const { all, alphaCapable } = configuredColours();
  const uses = fractionalUses(all);

  it("reads both sides of the question", () => {
    // A guard on the guard: a regex that quietly stopped matching would make
    // every assertion below vacuously true.
    expect(all.size).toBeGreaterThan(20);
    expect(alphaCapable.size).toBeGreaterThan(0);
    expect(uses.length).toBeGreaterThan(0);
  });

  it("only asks for an alpha from a token that can carry one", () => {
    const broken = uses.filter((use) => !alphaCapable.has(use.token));
    // Named in the failure, because "some class somewhere is transparent" is
    // the part that takes the afternoon.
    expect(
      broken.map((use) => `${use.token} at ${use.where}`),
      "these resolve to nothing and render fully transparent",
    ).toEqual([]);
  });

  it("declares channels in the stylesheet for every alpha-capable token", () => {
    const css = readFileSync(join(ROOT, "app", "globals.css"), "utf8");

    for (const token of alphaCapable) {
      const channels = [...css.matchAll(new RegExp(`--${token}-rgb:\\s*[\\d\\s]+;`, "g"))].length;
      const wrapped = [...css.matchAll(
        new RegExp(`--${token}:\\s*rgb\\(var\\(--${token}-rgb\\)\\);`, "g"),
      )].length;

      expect(channels, `--${token}-rgb is declared`).toBeGreaterThan(0);

      /*
       * Once per theme that overrides it — not "twice" flatly. A token whose
       * value is the same in both themes is declared once and correctly
       * inherits; --check-held is one, because the section it is drawn in is
       * dark whichever theme the page is in.
       *
       * What has to hold is that the two forms move together. The channels are
       * what Tailwind reads for `bg-x/40` and the wrapper is what every plain
       * `var(--x)` in the stylesheet reads, so a theme that redefines one and
       * not the other renders the same token as two different colours
       * depending on which spelling asked for it.
       */
      expect(wrapped, `--${token} is wrapped once per --${token}-rgb`).toBe(channels);
    }
  });
});
