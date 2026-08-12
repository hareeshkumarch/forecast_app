/*
 * The build sequence for the hero chart, as numbers rather than as prose.
 *
 * The order carries the product's claim: what happened is known, there is a
 * boundary at today, what comes after is a forecast, and the range around it
 * widens the further out it goes. The 160ms hold is the boundary — it is the
 * only pause in the sequence and it is there to be noticed.
 */
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
  };
}

/** When a given bar starts rising, measured from the first frame. */
export function barDelay(step: number, historyLength: number, timing: ScapeTiming): number {
  return step < historyLength
    ? step * HISTORY_STAGGER
    : timing.forecastStart + (step - historyLength) * FORECAST_STAGGER;
}

/** When a forecast bar's uncertainty shell starts expanding. */
export function shellDelay(step: number, historyLength: number, timing: ScapeTiming): number {
  return barDelay(step, historyLength, timing) + SHELL_FOLLOW;
}
