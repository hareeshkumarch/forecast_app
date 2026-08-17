export const BAR_RISE = 260;
export const HISTORY_STAGGER = 14;
export const TODAY_HOLD = 160;
export const FORECAST_STAGGER = 22;
export const SHELL_FOLLOW = 80;
export const SHELL_EXPAND = 340;
export const CAPTION_FADE = 200;

export const SEQUENCE_BUDGET = 1400;

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

export function scapeTiming(historyLength: number, futureLength: number): ScapeTiming {
  const historyEnd = Math.max(0, historyLength - 1) * HISTORY_STAGGER + BAR_RISE;
  const forecastStart = historyEnd + TODAY_HOLD;
  const lastForecast = forecastStart + Math.max(0, futureLength - 1) * FORECAST_STAGGER;
  const settled = lastForecast + SHELL_FOLLOW + SHELL_EXPAND;

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

export function barDelay(step: number, historyLength: number, timing: ScapeTiming): number {
  return step < historyLength
    ? step * timing.historyStagger
    : timing.forecastStart + (step - historyLength) * timing.forecastStagger;
}

export function shellDelay(step: number, historyLength: number, timing: ScapeTiming): number {
  return barDelay(step, historyLength, timing) + timing.shellFollow;
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
