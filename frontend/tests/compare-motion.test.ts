import { describe, expect, it } from "vitest";

import {
  COMPARE_BUDGET,
  HISTORY_DRAW,
  PANEL_STAGGER,
  compareSettled,
  panelTiming,
} from "@/lib/compare-motion";

const left = panelTiming(0);
const right = panelTiming(1);

describe("the panels draw in the order the argument is made", () => {
  it("draws the history before the forecast that continues it", () => {
    for (const panel of [left, right]) {
      expect(panel.forecast).toBe(panel.history + HISTORY_DRAW);
    }
  });

  it("lands the outcome only once the forecast it judges has finished", () => {
    for (const panel of [left, right]) {
      expect(panel.outcome).toBeGreaterThan(panel.forecast);
      expect(panel.settled).toBeGreaterThan(panel.outcome);
    }
  });

  it("runs the two panels in step, one trailing the other", () => {
    expect(right.history - left.history).toBe(PANEL_STAGGER);
    expect(right.forecast - left.forecast).toBe(PANEL_STAGGER);
    expect(right.outcome - left.outcome).toBe(PANEL_STAGGER);
  });

  it("starts the trailing panel before the leading one has finished, so they read as a pair", () => {
    expect(right.history).toBeLessThan(left.settled);
  });
});

describe("the wipe waits for the block it is inside", () => {
  it("gives the section's own fade a head start rather than drawing behind it", () => {
    expect(left.history).toBeGreaterThan(0);
  });
});

describe("the comparison stays within its budget", () => {
  it("settles before the reader has been asked to wait too long", () => {
    const settled = compareSettled(2);
    expect(settled).toBe(right.settled);
    expect(settled).toBeLessThan(COMPARE_BUDGET);
  });
});
