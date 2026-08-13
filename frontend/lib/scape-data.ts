import { RANGE_GROWTH, rangeLift } from "@/lib/demand-scape";

/**
 * The shapes the hero chart can be asked to draw.
 *
 * A planner arriving here wants to know whether this works on demand that
 * looks like theirs, and one curve cannot answer that. These three do not
 * differ in their numbers so much as in their behaviour — one drifts, one
 * peaks and falls, one spikes and settles — and each carries its own `growth`,
 * because a range that opened at the same rate for all three would be a
 * decoration rather than a claim.
 *
 * They are illustrations, not anyone's sales. Every series is the same length,
 * which is what keeps the drawing the same size as they swap: `buildScape`
 * sizes the frame from the step count, so equal counts mean the chart never
 * resizes under a chart the visitor is looking at.
 */
export type Scenario = {
  id: string;
  label: string;
  caption: string;
  history: number[];
  future: number[];
  growth: number;
};

export const SCENARIOS: Scenario[] = [
  {
    id: "grocery",
    label: "Grocery",
    caption: "Steady weekly demand, drifting down — Chilled in front, Ambient behind.",
    history: [
      72, 96, 84, 110, 91, 104, 81, 118, 89, 102, 78, 94, 72, 86, 68, 91, 74, 81, 64, 73, 61, 69,
      58, 76, 67, 72,
    ],
    future: [86, 106, 78, 101, 72, 91, 68, 83, 61],
    growth: RANGE_GROWTH,
  },
  {
    id: "fashion",
    label: "Fashion",
    caption: "A season that builds and falls away — Outerwear in front, Knitwear behind.",
    history: [
      38, 42, 47, 44, 53, 58, 55, 66, 71, 68, 80, 88, 84, 97, 105, 99, 112, 104, 96, 85, 78, 66,
      59, 51, 46, 42,
    ],
    future: [39, 36, 34, 31, 30, 28, 29, 27, 26],
    // A season turning is the hardest of the three to call, and the interval
    // it earns is the widest.
    growth: 0.075,
  },
  {
    id: "electronics",
    label: "Electronics",
    caption: "A launch, then a long settle — Audio in front, Accessories behind.",
    history: [
      24, 96, 118, 110, 96, 88, 79, 73, 68, 64, 61, 59, 57, 55, 53, 52, 50, 49, 48, 47, 46, 45, 45,
      44, 43, 43,
    ],
    future: [42, 42, 41, 41, 40, 40, 39, 39, 38],
    // Once a launch has decayed into a plateau there is little left to be
    // wrong about, and the interval closes to match.
    growth: 0.035,
  },
];

export const DEFAULT_SCENARIO = SCENARIOS[0] as Scenario;

export function scenarioById(id: string): Scenario {
  return SCENARIOS.find((scenario) => scenario.id === id) ?? DEFAULT_SCENARIO;
}

export type Readout = { label: string; point: string; range: string };

export function readoutFor(scenario: Scenario, step: number): Readout {
  const historyLength = scenario.history.length;

  if (step < historyLength) {
    const value = scenario.history[step] ?? 0;
    return {
      label: `${historyLength - step} weeks ago`,
      point: `${value} units sold`,
      range: "actual",
    };
  }

  const horizon = step - historyLength + 1;
  const value = scenario.future[step - historyLength] ?? 0;
  const spread = value * (rangeLift(horizon, scenario.growth) - 1);
  return {
    label: `Week +${horizon}`,
    point: `${Math.round(value)} units`,
    range: `${Math.round(value - spread)} to ${Math.round(value + spread)}`,
  };
}

/*
 * The forecast readouts share columns, and they share them across every
 * scenario rather than within one. The chart walks these weeks by itself on
 * load, and "86 units" giving way to "106 units" re-centres the whole line —
 * the page moving on its own, which is a layout shift on the way in and a
 * flinch to look at. Measuring the columns over all three scenarios costs
 * nothing and means switching between them does not move the line either.
 */
const FORECAST_READOUTS = SCENARIOS.flatMap((scenario) =>
  scenario.future.map((_, index) => readoutFor(scenario, scenario.history.length + index)),
);

const COLUMN = {
  point: Math.max(...FORECAST_READOUTS.map((readout) => readout.point.length)),
  range: Math.max(...FORECAST_READOUTS.map((readout) => readout.range.length)),
};

/** The same readout, laid out on those shared columns. Equal character counts
 *  are equal widths in the mono face the readout is set in. */
export function columned(readout: Readout): Readout {
  if (readout.range === "actual") return readout;
  return {
    label: readout.label,
    point: readout.point.padEnd(COLUMN.point),
    range: readout.range.padEnd(COLUMN.range),
  };
}
