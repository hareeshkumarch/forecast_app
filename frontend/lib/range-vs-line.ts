export type Point = { x: number; y: number };

export type Band = { upper: Point[]; lower: Point[] };

export type Outcome = {
  x: number;
  y: number;
  insideBand: boolean;
  onLine: boolean;
};

export type Panel = {
  width: number;
  height: number;
  baseline: number;
  history: Point[];
  projection: Point[];
  band: Band | null;
  outcome: Outcome;
  split: number;
};

const WIDTH = 320;
const HEIGHT = 168;
const PAD = { top: 16, right: 14, bottom: 26, left: 14 };

const HISTORY = [46, 52, 49, 58, 55, 63, 60, 69];
const PROJECTION = [72, 76, 80, 84];

const ACTUAL = 70;

const SPREAD_BASE = 0.08;
const SPREAD_GROWTH = 0.055;

export function spreadAt(step: number): number {
  return SPREAD_BASE + SPREAD_GROWTH * step;
}

function scaleFor(values: number[]): { top: number; bottom: number } {
  const peak = Math.max(...values);
  const floor = Math.min(...values);
  const pad = (peak - floor) * 0.18 || 1;
  return { top: peak + pad, bottom: Math.max(0, floor - pad) };
}

export function buildPanel(withBand: boolean): Panel {
  const steps = HISTORY.length + PROJECTION.length;
  const span = steps - 1;

  const plotWidth = WIDTH - PAD.left - PAD.right;
  const plotHeight = HEIGHT - PAD.top - PAD.bottom;

  const bounds = scaleFor([
    ...HISTORY,
    ...PROJECTION.map((value, index) => value * (1 + spreadAt(index + 1))),
    ...PROJECTION.map((value, index) => value * (1 - spreadAt(index + 1))),
    ACTUAL,
  ]);

  const x = (index: number) => PAD.left + (index / span) * plotWidth;
  const y = (value: number) => {
    const reach = bounds.top - bounds.bottom || 1;
    return PAD.top + plotHeight - ((value - bounds.bottom) / reach) * plotHeight;
  };

  const history = HISTORY.map((value, index) => ({ x: x(index), y: y(value) }));
  const last = HISTORY.length - 1;

  const projection = [
    { x: x(last), y: y(HISTORY[last] ?? 0) },
    ...PROJECTION.map((value, index) => ({ x: x(HISTORY.length + index), y: y(value) })),
  ];

  const band: Band | null = withBand
    ? {
        upper: [
          { x: x(last), y: y(HISTORY[last] ?? 0) },
          ...PROJECTION.map((value, index) => ({
            x: x(HISTORY.length + index),
            y: y(value * (1 + spreadAt(index + 1))),
          })),
        ],
        lower: [
          { x: x(last), y: y(HISTORY[last] ?? 0) },
          ...PROJECTION.map((value, index) => ({
            x: x(HISTORY.length + index),
            y: y(value * (1 - spreadAt(index + 1))),
          })),
        ],
      }
    : null;

  const finalStep = PROJECTION.length;
  const predicted = PROJECTION[finalStep - 1] ?? 0;
  const low = predicted * (1 - spreadAt(finalStep));
  const high = predicted * (1 + spreadAt(finalStep));

  return {
    width: WIDTH,
    height: HEIGHT,
    baseline: PAD.top + plotHeight,
    history,
    projection,
    band,
    outcome: {
      x: x(steps - 1),
      y: y(ACTUAL),
      insideBand: ACTUAL >= low && ACTUAL <= high,
      onLine: Math.abs(ACTUAL - predicted) < 1e-9,
    },
    split: x(last),
  };
}

export function path(points: Point[]): string {
  return points.map((point, index) => `${index === 0 ? "M" : "L"}${round(point.x)} ${round(point.y)}`).join(" ");
}

export function area(band: Band): string {
  const forward = band.upper.map((point) => `${round(point.x)} ${round(point.y)}`);
  const back = [...band.lower].reverse().map((point) => `${round(point.x)} ${round(point.y)}`);
  return `M${forward.join(" L")} L${back.join(" L")} Z`;
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}
