export const BAR_RISE = 260;
export const HISTORY_STAGGER = 11;
export const TODAY_HOLD = 160;
export const FORECAST_STAGGER = 22;
export const SHELL_FOLLOW = 80;
export const SHELL_EXPAND = 340;
export const CAPTION_FADE = 200;

export const SEQUENCE_BUDGET = 1400;

export const ROW_LEAD = 70;

export type ScapeTiming = {
  historyEnd: number;
  forecastStart: number;
  captionStart: number;
  settled: number;
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

export const DEMO_HOLD = 520;

export const DEMO_STEP = 220;

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
