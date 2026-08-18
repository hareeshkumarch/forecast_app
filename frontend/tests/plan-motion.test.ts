import { describe, expect, it } from "vitest";

import {
  BAND_GROW,
  FIRST_MARK,
  MARK_LAND,
  MARK_STAGGER,
  PLAN_BUDGET,
  markDelay,
  planSettled,
} from "@/lib/plan-motion";

const MARKS = 3;

describe("the band is a range before it is three figures", () => {
  it("opens the track before the first figure lands on it", () => {
    expect(markDelay(0)).toBeGreaterThan(0);
    expect(markDelay(0)).toBeLessThan(BAND_GROW);
  });

  it("lands the figures left to right, one at a time", () => {
    const delays = [0, 1, 2].map(markDelay);
    expect(delays).toEqual([...delays].sort((a, b) => a - b));
    expect(new Set(delays).size).toBe(delays.length);
    expect(delays[1]! - delays[0]!).toBe(MARK_STAGGER);
  });

  it("settles within the budget", () => {
    expect(planSettled(MARKS)).toBeLessThan(PLAN_BUDGET);
    expect(planSettled(MARKS)).toBeGreaterThanOrEqual(FIRST_MARK + MARK_LAND);
  });

  it("waits for the track before marking the ends", () => {
    expect(planSettled(MARKS)).toBeGreaterThanOrEqual(BAND_GROW + MARK_LAND);
  });
});
