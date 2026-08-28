export type Tone = "history" | "future" | "range";

/**
 * One row of the drawing: a product line with its own sales and its own
 * forecast, given front to back.
 *
 * The depth in this chart is the plan's second level, not an effect. Every row
 * is plotted on one shared vertical scale, so a bar in the back row and a bar
 * in the front row can be compared by eye and the two together add up to the
 * week the readout quotes. A row scaled to look good would make the third
 * dimension a decoration, and there is nothing to read in a decoration.
 */
export type Layer = {
  id: string;
  label: string;
  history: number[];
  future: number[];
};

export type Prism = {
  key: string;
  row: number;
  step: number;
  horizon: number;
  tone: Tone;
  x: number;
  baseY: number;
  width: number;
  height: number;
  extrudeX: number;
  extrudeY: number;
  shellFloor: number;
};

export type Guide = { key: string; x1: number; y1: number; x2: number; y2: number };

export type Label = {
  key: string;
  x: number;
  y: number;
  text: string;
  anchor: "start" | "middle" | "end";
};

export type Boundary = { x1: number; y1: number; x2: number; y2: number };

/** One row's slice of a week: the vertical band standing over that row's bar. */
export type Band = { key: string; x: number; y1: number; y2: number; width: number };

export type Column = {
  step: number;
  x: number;
  y1: number;
  y2: number;
  width: number;
  /*
   * A band per row, rather than one rectangle spanning both.
   *
   * The rows are offset along the depth axis, so a single upright rectangle
   * wide enough to cover the far row also covers the floor beside the near
   * one — a pale slab standing next to the week instead of behind it.
   *
   * Each band runs from its own row's baseline to just over the top of what
   * that row draws in that week, rather than to the top of the frame. A band
   * of fixed height is mostly empty sky above a short week, which reads as a
   * marker floating near the bar instead of one standing behind it.
   */
  bands: Band[];
};

export type Scape = {
  viewBox: string;
  width: number;
  height: number;
  prisms: Prism[];
  guides: Guide[];
  labels: Label[];
  /** One name per row, written where that row begins. */
  rowLabels: Label[];
  boundary: Boundary;
  columns: Column[];
  rows: number;
  steps: number;
  historyLength: number;
  futureLength: number;
};

const DEPTH_X = 940;
const DEPTH_Y = 190;
/* Taller than it was. At 208 the prisms were shorter than they were wide and
   the drawing read as a strip of texture; the height is what lets a bar look
   like an object standing on a floor rather than a tick on an axis. */
const PLOT_HEIGHT = 268;

/* A deeper step between rows. The two product lines used to sit close enough
   that the near row's top face touched the far row's front, which is exactly
   where an isometric drawing stops reading as depth and starts reading as one
   flat silhouette. */
const ROW_DX = 46;
const ROW_DY = 42;

const MAX_BAR = 46;
const BAR_FILL = 0.78;
const EXTRUDE_X_RATIO = 0.48;
const EXTRUDE_Y_RATIO = 0.24;

const RANGE_BASE = 1.05;
export const RANGE_GROWTH = 0.055;

/**
 * How far the range has opened by `horizon` weeks out.
 *
 * `growth` is a property of the series, not of the drawing: demand that jumps
 * about earns a wider interval than demand that settles, and a chart offering
 * to show more than one shape has to be able to say so.
 */
export function rangeLift(horizon: number, growth: number = RANGE_GROWTH): number {
  return RANGE_BASE + growth * horizon;
}

const LABEL_ADVANCE = 10.2;
const LABEL_PAD = 10;
const LONGEST_LEFT = "120 weeks ago".length;
const LONGEST_RIGHT = "+111 weeks".length;
/** The left gutter holds the row names as well as the oldest week, so it is
 *  sized for whichever of the two runs longer. A row named past this is not
 *  wrong, it is simply wider than the space reserved for it. */
export const LONGEST_ROW_NAME = 12;

const GUTTER = {
  left: Math.ceil(Math.max(LONGEST_LEFT, LONGEST_ROW_NAME) * LABEL_ADVANCE) + LABEL_PAD * 2,
  right: Math.ceil(LONGEST_RIGHT * LABEL_ADVANCE) + LABEL_PAD * 2,
  top: 34,
  bottom: 62,
};

/* Three, not seven. The floor lines are there so the bars have something to
   stand on; at seven they were a hatch pattern behind the subject, and the
   pale ones nearest the top were the first thing the eye found. */
const GUIDE_COUNT = 3;

/** Text sits a touch under the line it names, so it reads as sitting on it. */
const LABEL_DROP = 5;
/** How far the oldest-week caption clears the name of the back row. */
const PAST_LIFT = 26;

/** Air over the tallest mark in a week, so its band reads as standing behind
 *  the bar rather than being clipped to it. */
const BAND_HEADROOM = 12;

function extent(values: number[]): number {
  const peak = Math.max(...values, 0);
  return peak > 0 ? peak : 1;
}

export function buildScape(layers: Layer[], growth: number = RANGE_GROWTH): Scape {
  const rows = Math.max(layers.length, 1);
  const historyLength = Math.max(0, ...layers.map((layer) => layer.history.length));
  const futureLength = Math.max(0, ...layers.map((layer) => layer.future.length));
  const steps = historyLength + futureLength;

  const span = Math.max(steps - 1, 1);

  const provisional = DEPTH_X / span;
  const width = Math.min(provisional * BAR_FILL, MAX_BAR);
  const extrudeX = width * EXTRUDE_X_RATIO;
  const extrudeY = width * EXTRUDE_Y_RATIO;

  const dx = (DEPTH_X - ROW_DX - width - extrudeX) / span;
  const dy = (DEPTH_Y - ROW_DY) / span;

  // One scale for every row, taken from the tallest thing any row has to
  // draw — which is a range shell, not a bar, wherever the forecast reaches
  // further than the history did.
  const scale =
    (PLOT_HEIGHT - extrudeY) /
    extent(
      layers.flatMap((layer) => [
        ...layer.history,
        ...layer.future.map((value, index) => value * rangeLift(index + 1, growth)),
      ]),
    );

  const prisms: Prism[] = [];

  for (let row = rows - 1; row >= 0; row--) {
    const layer = layers[row];
    for (let step = 0; step < steps; step++) {
      const x = step * dx + row * ROW_DX;
      const baseY = step * dy - row * ROW_DY;
      const historical = step < historyLength;
      const horizon = historical ? 0 : step - historyLength + 1;
      const value =
        (historical ? layer?.history[step] : layer?.future[step - historyLength]) ?? 0;
      const lift = historical ? 1 : rangeLift(horizon, growth);

      if (!historical) {
        prisms.push({
          key: `range-${row}-${step}`,
          row,
          step,
          horizon,
          tone: "range",
          x,
          baseY,
          width,
          height: value * lift * scale,
          extrudeX,
          extrudeY,
          shellFloor: 1 / lift,
        });
      }

      prisms.push({
        key: `${historical ? "history" : "future"}-${row}-${step}`,
        row,
        step,
        horizon,
        tone: historical ? "history" : "future",
        x,
        baseY,
        width,
        height: value * scale,
        extrudeX,
        extrudeY,
        shellFloor: 0,
      });
    }
  }

  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  // The highest point each row reaches in each week, shells included — what a
  // band has to clear to stand behind everything drawn there.
  const ceilings = new Map<string, number>();
  for (const prism of prisms) {
    const top = prism.baseY - prism.height - prism.extrudeY;
    minX = Math.min(minX, prism.x);
    maxX = Math.max(maxX, prism.x + prism.width + prism.extrudeX);
    minY = Math.min(minY, top);
    maxY = Math.max(maxY, prism.baseY);

    const key = `${prism.row}-${prism.step}`;
    ceilings.set(key, Math.min(ceilings.get(key) ?? Infinity, top));
  }

  minX = Math.min(minX, 0);
  maxX = Math.max(maxX, DEPTH_X);
  minY = Math.min(minY, -(rows - 1) * ROW_DY - PLOT_HEIGHT);
  maxY = Math.max(maxY, DEPTH_Y - ROW_DY);

  const left = minX - GUTTER.left;
  const top = minY - GUTTER.top;
  const boxWidth = maxX - minX + GUTTER.left + GUTTER.right;
  const boxHeight = maxY - minY + GUTTER.top + GUTTER.bottom;

  const todayX = historyLength * dx - dx / 2;
  const todayY = historyLength * dy - dy / 2 - (rows - 1) * ROW_DY;

  const boundary: Boundary = {
    x1: todayX,
    y1: minY,
    x2: todayX,
    y2: todayY + ROW_DY,
  };

  const run = maxX - minX - ROW_DX - width - extrudeX;
  const guides: Guide[] = [];
  for (let index = 0; index < GUIDE_COUNT; index++) {
    const lift = (index / (GUIDE_COUNT - 1)) * (maxY - dy * span - minY);
    guides.push({
      key: `floor-${index}`,
      x1: minX,
      y1: minY + lift,
      x2: minX + run,
      y2: minY + lift + dy * span,
    });
  }

  /*
   * Time runs down the diagonal, so the oldest week is at the top left and the
   * horizon at the bottom right — the two captions sit at the ends of that
   * diagonal rather than along the bottom of the frame, where they would point
   * at empty floor. "today" is the exception: it belongs under the line that
   * divides the two, which is the one place in the frame that is horizontal.
   *
   * The oldest-week caption clears the rows by sitting above the back one. The
   * left gutter below it belongs to the row names, and the two competing for
   * the same baseline is what the lift is buying.
   */
  const labels: Label[] = [
    {
      key: "past",
      x: left + LABEL_PAD,
      y: -(rows - 1) * ROW_DY - PAST_LIFT,
      text: `${historyLength} weeks ago`,
      anchor: "start",
    },
    {
      key: "today",
      x: todayX,
      y: maxY + GUTTER.bottom * 0.62,
      text: "today",
      anchor: "middle",
    },
    {
      key: "horizon",
      x: left + boxWidth - LABEL_PAD,
      y: maxY - GUTTER.bottom * 0.06,
      text: `+${futureLength} weeks`,
      anchor: "end",
    },
  ];

  // Written against the left edge of the plot rather than each row's own first
  // bar: staggering them along the depth axis puts the back row's name over the
  // front row's opening weeks, which is exactly where its bars are.
  const rowLabels: Label[] = layers.map((layer, row) => ({
    key: `row-${layer.id}`,
    x: -LABEL_PAD,
    y: -row * ROW_DY + LABEL_DROP,
    text: layer.label,
    anchor: "end",
  }));

  const columns: Column[] = Array.from({ length: steps }, (_, step) => {
    const front = step * dx;
    const back = front + (rows - 1) * ROW_DX + width + extrudeX;
    return {
      step,
      x: front,
      width: back - front,
      y1: minY,
      y2: step * dy,
      bands: Array.from({ length: rows }, (_, row) => {
        const floor = step * dy - row * ROW_DY;
        const ceiling = ceilings.get(`${row}-${step}`) ?? floor;
        return {
          key: `band-${row}`,
          x: front + row * ROW_DX,
          width: width + extrudeX,
          y1: ceiling - BAND_HEADROOM,
          y2: floor,
        };
      }),
    };
  });

  return {
    viewBox: `${round(left)} ${round(top)} ${round(boxWidth)} ${round(boxHeight)}`,
    width: round(boxWidth),
    height: round(boxHeight),
    prisms,
    guides,
    labels,
    rowLabels,
    boundary,
    columns,
    rows,
    steps,
    historyLength,
    futureLength,
  };
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

export function prismFaces(prism: Prism): {
  front: string;
  side: string;
  top: string;
} {
  const { x, baseY, width, height, extrudeX, extrudeY } = prism;
  const top = baseY - height;
  return {
    front: `${x},${top} ${x + width},${top} ${x + width},${baseY} ${x},${baseY}`,
    side: `${x + width},${top} ${x + width + extrudeX},${top - extrudeY} ${x + width + extrudeX},${baseY - extrudeY} ${x + width},${baseY}`,
    top: `${x},${top} ${x + extrudeX},${top - extrudeY} ${x + width + extrudeX},${top - extrudeY} ${x + width},${top}`,
  };
}

export function labelWidth(text: string): number {
  return text.length * LABEL_ADVANCE;
}

export function scapeVertices(scape: Scape): Array<[number, number]> {
  const points: Array<[number, number]> = [];
  for (const prism of scape.prisms) {
    const faces = prismFaces(prism);
    for (const face of [faces.front, faces.side, faces.top]) {
      for (const pair of face.split(" ")) {
        const [x, y] = pair.split(",").map(Number);
        if (x !== undefined && y !== undefined) points.push([x, y]);
      }
    }
  }
  return points;
}
