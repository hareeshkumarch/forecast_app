export const HISTORY_DRAW = 340;

export const FORECAST_DRAW = 320;

export const OUTCOME_LAND = 260;

export const PANEL_STAGGER = 130;

const REVEAL_LEAD = 140;

const OUTCOME_GAP = 70;

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
