export const BAR_RISE = 260;
export const HISTORY_STAGGER = 11;
export const TODAY_HOLD = 160;
export const FORECAST_STAGGER = 22;
export const SHELL_FOLLOW = 80;
export const SHELL_EXPAND = 340;
export const CAPTION_FADE = 200;

export const SEQUENCE_BUDGET = 1400;

/**
 * How far ahead of the row in front of it a row behind starts.
 *
 * The two rows used to arrive together, which drew the chart as one object
 * with a texture rather than as two product lines standing one behind the
 * other. Building away-to-near assembles the depth instead of asserting it:
 * the far line lands, and the near line arrives in front of something that is
 * already there.
 *
 * Small on purpose. This is a beat between two rows, not a second sequence —
 * at much more than this the chart reads as being drawn twice, and the whole
 * build has 1.4 seconds to spend. `HISTORY_STAGGER` came down from 14 to pay
 * for it.
 */
export const ROW_LEAD = 70;

export type ScapeTiming = {
  historyEnd: number;
  forecastStart: number;
  captionStart: number;
  settled: number;
  /** Durations the marks animate over. */
  rise: number;
  expand: number;
  captionFade: number;
  historyStagger: number;
  forecastStagger: number;
  shellFollow: number;
};

export function scapeTiming(
  historyLength: number,
  futureLength: number,
  rows = 1,
): ScapeTiming {
  const historyEnd = Math.max(0, historyLength - 1) * HISTORY_STAGGER + BAR_RISE;
  const forecastStart = historyEnd + TODAY_HOLD;
  const lastForecast = forecastStart + Math.max(0, futureLength - 1) * FORECAST_STAGGER;
  // The nearest row is the last to arrive, so the sequence is not settled
  // until its lead has been spent as well.
  const settled = lastForecast + rowLead(0, rows) + SHELL_FOLLOW + SHELL_EXPAND;

  return {
    historyEnd,
    forecastStart,
    captionStart: Math.max(0, settled - CAPTION_FADE),
    settled,
    rise: BAR_RISE,
    expand: SHELL_EXPAND,
    captionFade: CAPTION_FADE,
    historyStagger: HISTORY_STAGGER,
    forecastStagger: FORECAST_STAGGER,
    shellFollow: SHELL_FOLLOW,
  };
}

/** How long a row waits before it starts, counting from the back row forward. */
export function rowLead(row: number, rows: number): number {
  return Math.max(0, rows - 1 - row) * ROW_LEAD;
}

export function barDelay(
  step: number,
  historyLength: number,
  timing: ScapeTiming,
  row = 0,
  rows = 1,
): number {
  const week =
    step < historyLength
      ? step * timing.historyStagger
      : timing.forecastStart + (step - historyLength) * timing.forecastStagger;
  return week + rowLead(row, rows);
}

export function shellDelay(
  step: number,
  historyLength: number,
  timing: ScapeTiming,
  row = 0,
  rows = 1,
): number {
  return barDelay(step, historyLength, timing, row, rows) + timing.shellFollow;
}

/*
 * The chart asks to be hovered, and then waits. Most visitors will not hover a
 * chart on a page they have been on for two seconds, so the readout — the part
 * that actually shows what the product does with a week — goes unseen. Rather
 * than ask harder, the chart walks its own forecast once and shows them.
 *
 * It runs after the build has settled, over the forecast weeks only: the past
 * reads out as "actual", which demonstrates nothing that the bars have not
 * already said. Any real pointer, key or touch takes it back for good.
 */

/** A beat between the chart settling and the walk starting, so the two read as
 *  two things rather than one long animation. */
export const DEMO_HOLD = 520;

/** One forecast week to the next. Fast enough to read as a scrub of the whole
 *  horizon, slow enough that the numbers underneath are legibly changing. */
export const DEMO_STEP = 220;

/** The last week is held, so at least one readout can actually be read before
 *  the hint comes back. */
export const DEMO_LINGER = 760;

export type DemoWalk = {
  start: number;
  steps: number[];
  interval: number;
  release: number;
};

export function demoWalk(
  historyLength: number,
  futureLength: number,
  timing: ScapeTiming,
): DemoWalk {
  const start = timing.settled + DEMO_HOLD;
  const steps = Array.from({ length: futureLength }, (_, index) => historyLength + index);
  const last = start + Math.max(steps.length - 1, 0) * DEMO_STEP;
  return { start, steps, interval: DEMO_STEP, release: last + DEMO_LINGER };
}
