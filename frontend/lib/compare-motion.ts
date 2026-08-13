/**
 * Timing for the two comparison panels.
 *
 * The section's argument has an order to it — this is the history you already
 * have, this is the forecast drawn from it, this is what actually happened —
 * and the motion tells it in that order rather than presenting the finished
 * charts and asking the reader to work out which part came first.
 */

/** The shared history, drawn from the left edge to the handoff. */
export const HISTORY_DRAW = 340;

/** The forecast and, on the ranged panel, the range that belongs to it. They
 *  wipe together: the range is not a second thing that arrives afterwards. */
export const FORECAST_DRAW = 320;

/** The outcome dropping onto the chart. */
export const OUTCOME_LAND = 260;

/** The right panel trails the left, so the pair reads as one sentence rather
 *  than as two charts that happened to animate at the same moment. */
export const PANEL_STAGGER = 130;

/**
 * The `Reveal` around the section fades the whole block in over 320ms. Drawing
 * from zero would spend the first third of the sequence behind that fade;
 * waiting for it to finish leaves a dead beat. This starts the wipe once the
 * block is mostly there.
 */
const REVEAL_LEAD = 140;

/** The outcome waits for the forecast it is judging to finish arriving. */
const OUTCOME_GAP = 70;

/** What the whole comparison must settle within. Asserted by the tests. */
export const COMPARE_BUDGET = 1400;

export type PanelTiming = {
  history: number;
  forecast: number;
  outcome: number;
  settled: number;
};

export function panelTiming(index: number): PanelTiming {
  const history = REVEAL_LEAD + index * PANEL_STAGGER;
  const forecast = history + HISTORY_DRAW;
  const outcome = forecast + FORECAST_DRAW + OUTCOME_GAP;
  return { history, forecast, outcome, settled: outcome + OUTCOME_LAND };
}

export function compareSettled(panels: number): number {
  return panelTiming(Math.max(panels - 1, 0)).settled;
}
