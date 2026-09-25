import { rangeLift, type Layer } from "@/lib/demand-scape";

export type Series = {
  label: string;
  caption: string;
  layers: Layer[];
  growth: number;
};

export const SERIES: Series = {
  label: "Grocery",
  caption: "Illustrative sales / Chilled in front / Ambient behind.",
  layers: [
    {
      id: "chilled",
      label: "Chilled",
      history: [32, 38, 30, 39, 34, 41, 35, 44, 37, 46, 39, 49, 57, 47, 40, 45],
      future: [38, 43, 36, 42, 35, 40, 33, 39],
    },
    {
      id: "ambient",
      label: "Ambient",
      history: [66, 70, 64, 72, 68, 74, 69, 78, 73, 80, 76, 84, 92, 86, 79, 83],
      future: [76, 81, 74, 79, 72, 77, 70, 75],
    },
  ],
  growth: 0.03,
};

export const HISTORY_WEEKS = Math.max(...SERIES.layers.map((layer) => layer.history.length));
export const FUTURE_WEEKS = Math.max(...SERIES.layers.map((layer) => layer.future.length));
export const WEEKS = HISTORY_WEEKS + FUTURE_WEEKS;

export function valueAt(layer: Layer, step: number): number {
  const value =
    step < layer.history.length
      ? layer.history[step]
      : layer.future[step - layer.history.length];
  return value ?? 0;
}

export type Readout = {
  label: string;
  point: string;
  range: string;
  split: string;
};

function splitFor(step: number): string {
  return SERIES.layers
    .map((layer) => `${layer.label} ${Math.round(valueAt(layer, step))}`)
    .join(" · ");
}

export function readoutFor(step: number): Readout {
  const total = SERIES.layers.reduce((sum, layer) => sum + valueAt(layer, step), 0);
  const split = splitFor(step);

  if (step < HISTORY_WEEKS) {
    return {
      label: `${HISTORY_WEEKS - step} weeks ago`,
      point: `${Math.round(total)} units sold`,
      range: "actual",
      split,
    };
  }

  const horizon = step - HISTORY_WEEKS + 1;
  const spread = total * (rangeLift(horizon, SERIES.growth) - 1);
  return {
    label: `Week +${horizon}`,
    point: `${Math.round(total)} units`,
    range: `${Math.round(total - spread)} to ${Math.round(total + spread)}`,
    split,
  };
}

const FORECAST_READOUTS = Array.from({ length: FUTURE_WEEKS }, (_, index) =>
  readoutFor(HISTORY_WEEKS + index),
);

const COLUMN = {
  point: Math.max(...FORECAST_READOUTS.map((readout) => readout.point.length)),
  range: Math.max(...FORECAST_READOUTS.map((readout) => readout.range.length)),
  split: Math.max(...FORECAST_READOUTS.map((readout) => readout.split.length)),
};

export function columned(readout: Readout): Readout {
  if (readout.range === "actual") return readout;
  return {
    label: readout.label,
    point: readout.point.padEnd(COLUMN.point),
    range: readout.range.padEnd(COLUMN.range),
    split: readout.split.padEnd(COLUMN.split),
  };
}

export function seriesDescription(): string {
  const lines = SERIES.layers.map((layer) => layer.label).join(" and ");
  return `${SERIES.label} demand for ${lines}: ${HISTORY_WEEKS} weeks of sales, then a ${FUTURE_WEEKS}-week forecast and the range each week could move within.`;
}
