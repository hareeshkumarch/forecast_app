import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

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

function fractionalUses(names: Set<string>): { token: string; where: string }[] {
  const prefixes = "bg|text|border|fill|stroke|from|via|to|ring|shadow|decoration|outline|divide|placeholder|caret|accent";
  const pattern = new RegExp(`\\b(?:${prefixes})-([\\w-]+)\\/\\d+`, "g");

  const uses: { token: string; where: string }[] = [];
  for (const dir of SOURCE_DIRS) {
    for (const file of sourceFiles(dir)) {
      const text = readFileSync(file, "utf8");
      for (const [, token] of text.matchAll(pattern)) {
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
    expect(all.size).toBeGreaterThan(20);
    expect(alphaCapable.size).toBeGreaterThan(0);
    expect(uses.length).toBeGreaterThan(0);
  });

  it("only asks for an alpha from a token that can carry one", () => {
    const broken = uses.filter((use) => !alphaCapable.has(use.token));
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

      expect(wrapped, `--${token} is wrapped once per --${token}-rgb`).toBe(channels);
    }
  });
});
