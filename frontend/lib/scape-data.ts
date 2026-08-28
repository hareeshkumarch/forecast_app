import { rangeLift, type Layer } from "@/lib/demand-scape";

/**
 * The demand the hero chart draws.
 *
 * One example, not a gallery of them. A visitor arriving here is deciding
 * whether a forecast is worth their sales history, and the question they are
 * actually asking — what does this thing hand me back? — is answered by one
 * chart read properly, never by three charts skimmed.
 *
 * What the one example has to earn is its depth. The two rows are the two
 * product lines a grocery plan is actually made of: they carry their own
 * sales, their own forecast and their own range, they are drawn on one shared
 * scale so they can be compared by eye, and they add up to the week the
 * readout quotes. That is the product's second claim — every level of the
 * plan — drawn rather than asserted.
 *
 * They are illustrations, not anyone's sales.
 */
export type Series = {
  label: string;
  caption: string;
  /** Front row first. The front line is the smaller of the two, so it never
   *  stands in front of the row behind it and hides the week being read. */
  layers: Layer[];
  growth: number;
};

export const SERIES: Series = {
  label: "Grocery",
  caption: "One grocery plan, two product lines deep — Chilled in front, Ambient behind.",
  /*
   * Steady weekly demand with a fortnightly rhythm, a promotion in week 13 and
   * a slow settle afterwards. Not a flat line, because a flat line needs no
   * forecast; not a cliff either, because the range would then be the only
   * thing on the chart worth looking at.
   */
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
  /*
   * Narrower than the drawing's default. Weekly grocery demand is about the
   * most predictable thing a planner owns, and an interval that had doubled by
   * the ninth week would be describing a different business — a range is a
   * claim about this demand, so it has to be the range this demand earns.
   */
  growth: 0.03,
};

export const HISTORY_WEEKS = Math.max(...SERIES.layers.map((layer) => layer.history.length));
export const FUTURE_WEEKS = Math.max(...SERIES.layers.map((layer) => layer.future.length));
export const WEEKS = HISTORY_WEEKS + FUTURE_WEEKS;

/** What one product line sold, or is forecast to sell, in a given week. */
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
  /** The same week, one level down: what each product line contributes. */
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

/*
 * The forecast readouts share columns. The chart walks these weeks by itself
 * on load, and "105 units" giving way to "116 units" re-centres the whole line
 * — the page moving on its own, which is a layout shift on the way in and a
 * flinch to look at. Measuring the widest of each field once and holding every
 * week to it costs nothing and keeps the line still.
 */
const FORECAST_READOUTS = Array.from({ length: FUTURE_WEEKS }, (_, index) =>
  readoutFor(HISTORY_WEEKS + index),
);

const COLUMN = {
  point: Math.max(...FORECAST_READOUTS.map((readout) => readout.point.length)),
  range: Math.max(...FORECAST_READOUTS.map((readout) => readout.range.length)),
  split: Math.max(...FORECAST_READOUTS.map((readout) => readout.split.length)),
};

/** The same readout, laid out on those shared columns. Equal character counts
 *  are equal widths in the mono face the readout is set in. */
export function columned(readout: Readout): Readout {
  if (readout.range === "actual") return readout;
  return {
    label: readout.label,
    point: readout.point.padEnd(COLUMN.point),
    range: readout.range.padEnd(COLUMN.range),
    split: readout.split.padEnd(COLUMN.split),
  };
}

/** What the chart is, for a screen reader that will never see it. */
export function seriesDescription(): string {
  const lines = SERIES.layers.map((layer) => layer.label).join(" and ");
  return `${SERIES.label} demand for ${lines}: ${HISTORY_WEEKS} weeks of sales, then a ${FUTURE_WEEKS}-week forecast and the range each week could move within.`;
}
