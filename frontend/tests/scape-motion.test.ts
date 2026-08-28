import { describe, expect, it } from "vitest";

import {
  DEMO_HOLD,
  DEMO_LINGER,
  ROW_LEAD,
  SEQUENCE_BUDGET,
  barDelay,
  demoWalk,
  scapeTiming,
  shellDelay,
} from "@/lib/scape-motion";

const HISTORY = 26;
const FUTURE = 9;
const ROWS = 2;

const timing = scapeTiming(HISTORY, FUTURE, ROWS);
const walk = demoWalk(HISTORY, FUTURE, timing);

describe("the build sequence", () => {
  it("runs the history, holds at today, then runs the forecast", () => {
    expect(barDelay(HISTORY - 1, HISTORY, timing)).toBeLessThan(timing.forecastStart);
    expect(barDelay(HISTORY, HISTORY, timing)).toBe(timing.forecastStart);
  });

  it("opens each range shell after the forecast it belongs to", () => {
    for (let step = HISTORY; step < HISTORY + FUTURE; step++) {
      expect(shellDelay(step, HISTORY, timing)).toBeGreaterThan(barDelay(step, HISTORY, timing));
    }
  });

  it("settles within its budget", () => {
    expect(timing.settled).toBeGreaterThan(0);
    expect(timing.settled).toBeLessThan(SEQUENCE_BUDGET);
  });

  it("runs the weeks in order", () => {
    const delays = Array.from({ length: HISTORY + FUTURE }, (_, step) =>
      barDelay(step, HISTORY, timing),
    );
    expect(delays).toEqual([...delays].sort((a, b) => a - b));
  });
});

describe("building the depth away-to-near", () => {
  it("starts the row behind before the row in front of it", () => {
    for (let step = 0; step < HISTORY + FUTURE; step++) {
      expect(barDelay(step, HISTORY, timing, 1, ROWS)).toBeLessThan(
        barDelay(step, HISTORY, timing, 0, ROWS),
      );
    }
  });

  it("gives every row the same lead, so the two never drift apart", () => {
    const gaps = Array.from({ length: HISTORY + FUTURE }, (_, step) =>
      barDelay(step, HISTORY, timing, 0, ROWS) - barDelay(step, HISTORY, timing, 1, ROWS),
    );
    expect(new Set(gaps).size).toBe(1);
    expect(gaps[0]).toBe(ROW_LEAD);
  });

  it("keeps a shell behind the forecast bar it wraps, in its own row", () => {
    for (let row = 0; row < ROWS; row++) {
      expect(shellDelay(HISTORY, HISTORY, timing, row, ROWS)).toBeGreaterThan(
        barDelay(HISTORY, HISTORY, timing, row, ROWS),
      );
    }
  });

  it("still settles inside the budget once the lead is paid for", () => {
    // The nearest row is the last to arrive, so the budget has to cover it.
    const lastBar = barDelay(HISTORY + FUTURE - 1, HISTORY, timing, 0, ROWS);
    expect(lastBar + timing.shellFollow + timing.expand).toBeLessThanOrEqual(timing.settled);
    expect(timing.settled).toBeLessThan(SEQUENCE_BUDGET);
  });

  it("costs nothing when there is only one row", () => {
    expect(scapeTiming(HISTORY, FUTURE, 1).settled).toBeLessThan(timing.settled);
    expect(barDelay(0, HISTORY, timing, 0, 1)).toBe(0);
  });
});

describe("the chart demonstrating its own readout", () => {
  it("waits for the build to settle before it starts", () => {
    expect(walk.start).toBe(timing.settled + DEMO_HOLD);
    expect(walk.start).toBeGreaterThan(timing.settled);
  });

  it("walks the forecast weeks, and only those", () => {
    expect(walk.steps).toHaveLength(FUTURE);
    expect(walk.steps[0]).toBe(HISTORY);
    expect(walk.steps.at(-1)).toBe(HISTORY + FUTURE - 1);
  });

  it("moves forward one week at a time without doubling back", () => {
    expect(walk.steps).toEqual([...walk.steps].sort((a, b) => a - b));
    expect(new Set(walk.steps).size).toBe(walk.steps.length);
  });

  it("holds the last week before handing the chart back", () => {
    const last = walk.start + (walk.steps.length - 1) * walk.interval;
    expect(walk.release).toBeGreaterThan(last + walk.interval);
  });

  it("never asks a step to land before the one before it", () => {
    const landings = walk.steps.map((_, index) => walk.start + index * walk.interval);
    expect(landings).toEqual([...landings].sort((a, b) => a - b));
    expect(landings.at(-1)).toBeLessThan(walk.release);
  });

  it("stays a demonstration rather than an animation the visitor waits out", () => {
    // From the chart settling to the hint coming back.
    expect(walk.release - timing.settled).toBeLessThan(4000);
  });

  it("has nothing to walk when there is no forecast", () => {
    const empty = demoWalk(HISTORY, 0, timing);
    expect(empty.steps).toEqual([]);
    expect(empty.release).toBe(empty.start + DEMO_LINGER);
  });
});
