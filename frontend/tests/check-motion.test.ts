import { describe, expect, it } from "vitest";

import {
  BAR_RISE,
  CHECK_BUDGET,
  HELD_GAP,
  ROW_ADVANCE,
  checkDelay,
  checkSettled,
} from "@/lib/check-motion";

const ROWS = 3;
const TOTAL = 20;
const SHOWN = 13;

const row = (index: number, mark: Parameters<typeof checkDelay>[3]) =>
  checkDelay(index, mark === "bar" ? 0 : SHOWN, SHOWN, mark);

describe("the three steps read as three steps", () => {
  it("starts each row after the one above it", () => {
    const starts = [0, 1, 2].map((index) => row(index, "bar"));
    expect(starts).toEqual([...starts].sort((a, b) => a - b));
    expect(new Set(starts).size).toBe(starts.length);
  });

  it("starts a row before the one above it has settled, so it reads as one argument", () => {
    for (const index of [1, 2]) {
      const above = checkDelay(index - 1, TOTAL - 1, SHOWN, "bar") + BAR_RISE;
      expect(row(index, "bar")).toBeLessThan(above);
    }
  });

  it("holds the weeks that were hidden back behind the ones that were not", () => {
    for (const index of [1, 2]) {
      const lastShown = checkDelay(index, SHOWN - 1, SHOWN, "bar");
      expect(row(index, "held")).toBeGreaterThanOrEqual(lastShown + HELD_GAP);
    }
  });

  it("lands the outcome rule after the bar it is judging has started rising", () => {
    for (let index = SHOWN; index < TOTAL; index++) {
      const bar = checkDelay(2, index, SHOWN, "held");
      const tick = checkDelay(2, index, SHOWN, "tick");
      expect(tick).toBeGreaterThan(bar);
      expect(tick).toBeLessThan(bar + BAR_RISE);
    }
  });
});

describe("every row draws left to right", () => {
  it("never sends a later week ahead of an earlier one", () => {
    for (let index = 0; index < ROWS; index++) {
      const shownWeeks = Array.from({ length: SHOWN }, (_, week) =>
        checkDelay(index, week, SHOWN, "bar"),
      );
      const heldWeeks = Array.from({ length: TOTAL - SHOWN }, (_, week) =>
        checkDelay(index, SHOWN + week, SHOWN, "held"),
      );

      for (const group of [shownWeeks, heldWeeks]) {
        expect(group).toEqual([...group].sort((a, b) => a - b));
        expect(new Set(group).size).toBe(group.length);
      }
    }
  });

  it("never gives a mark a negative delay", () => {
    for (let index = 0; index < ROWS; index++) {
      for (let week = 0; week < TOTAL; week++) {
        expect(checkDelay(index, week, SHOWN, "bar")).toBeGreaterThanOrEqual(0);
      }
    }
  });
});

describe("the sequence stays within its budget", () => {
  it("settles before the reader has been asked to wait too long", () => {
    const settled = checkSettled(ROWS, TOTAL, SHOWN);
    expect(settled).toBeGreaterThan(0);
    expect(settled).toBeLessThan(CHECK_BUDGET);
  });

  it("scales with the rows it is given rather than assuming three", () => {
    expect(checkSettled(4, TOTAL, SHOWN) - checkSettled(3, TOTAL, SHOWN)).toBe(ROW_ADVANCE);
  });
});
