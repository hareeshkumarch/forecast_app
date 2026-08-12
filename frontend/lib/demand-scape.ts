export type Tone = "history" | "future" | "range";

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

export type Column = { step: number; x: number; y1: number; y2: number; width: number };

export type Scape = {
  viewBox: string;
  width: number;
  height: number;
  prisms: Prism[];
  guides: Guide[];
  labels: Label[];
  boundary: Boundary;
  columns: Column[];
  rows: number;
  steps: number;
};

const DEPTH_X = 940;
const DEPTH_Y = 190;
const PLOT_HEIGHT = 208;

const ROW_DX = 38;
const ROW_DY = 34;
const ROW_SCALE = [0.54, 0.72];

const MAX_BAR = 34;
const BAR_FILL = 0.78;
const EXTRUDE_X_RATIO = 0.48;
const EXTRUDE_Y_RATIO = 0.24;

const RANGE_BASE = 1.05;
const RANGE_GROWTH = 0.055;

export function rangeLift(horizon: number): number {
  return RANGE_BASE + RANGE_GROWTH * horizon;
}

const LABEL_ADVANCE = 10.2;
const LABEL_PAD = 10;
const LONGEST_LEFT = "120 weeks ago".length;
const LONGEST_RIGHT = "+111 weeks".length;

const GUTTER = {
  left: Math.ceil(LONGEST_LEFT * LABEL_ADVANCE) + LABEL_PAD * 2,
  right: Math.ceil(LONGEST_RIGHT * LABEL_ADVANCE) + LABEL_PAD * 2,
  top: 34,
  bottom: 62,
};

const GUIDE_COUNT = 7;

function extent(values: number[]): number {
  const peak = Math.max(...values, 0);
  return peak > 0 ? peak : 1;
}

export function buildScape(history: number[], future: number[]): Scape {
  const steps = history.length + future.length;
  const rows = ROW_SCALE.length;

  const span = Math.max(steps - 1, 1);

  const provisional = DEPTH_X / span;
  const width = Math.min(provisional * BAR_FILL, MAX_BAR);
  const extrudeX = width * EXTRUDE_X_RATIO;
  const extrudeY = width * EXTRUDE_Y_RATIO;

  const dx = (DEPTH_X - ROW_DX - width - extrudeX) / span;
  const dy = (DEPTH_Y - ROW_DY) / span;

  const tallestRow = Math.max(...ROW_SCALE);
  const scale =
    (PLOT_HEIGHT - extrudeY) /
    (extent([
      ...history,
      ...future.map((value, index) => value * rangeLift(index + 1)),
    ]) *
      tallestRow);

  const prisms: Prism[] = [];

  for (let row = rows - 1; row >= 0; row--) {
    const rowScale = ROW_SCALE[row] ?? 1;
    for (let step = 0; step < steps; step++) {
      const x = step * dx + row * ROW_DX;
      const baseY = step * dy - row * ROW_DY;
      const historical = step < history.length;
      const horizon = historical ? 0 : step - history.length + 1;
      const value = (historical ? history[step] : future[step - history.length]) ?? 0;
      const lift = historical ? 1 : rangeLift(horizon);

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
          height: value * lift * scale * rowScale,
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
        height: value * scale * rowScale,
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
  for (const prism of prisms) {
    const top = prism.baseY - prism.height;
    minX = Math.min(minX, prism.x);
    maxX = Math.max(maxX, prism.x + prism.width + prism.extrudeX);
    minY = Math.min(minY, top - prism.extrudeY);
    maxY = Math.max(maxY, prism.baseY);
  }

  minX = Math.min(minX, 0);
  maxX = Math.max(maxX, DEPTH_X);
  minY = Math.min(minY, -(rows - 1) * ROW_DY - PLOT_HEIGHT);
  maxY = Math.max(maxY, DEPTH_Y - ROW_DY);

  const left = minX - GUTTER.left;
  const top = minY - GUTTER.top;
  const boxWidth = maxX - minX + GUTTER.left + GUTTER.right;
  const boxHeight = maxY - minY + GUTTER.top + GUTTER.bottom;

  const todayX = history.length * dx - dx / 2;
  const todayY = history.length * dy - dy / 2 - (rows - 1) * ROW_DY;

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

  const labels: Label[] = [
    {
      key: "past",
      x: left + LABEL_PAD,
      y: 0,
      text: `${history.length} weeks ago`,
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
      text: `+${future.length} weeks`,
      anchor: "end",
    },
  ];

  const columns: Column[] = Array.from({ length: steps }, (_, step) => {
    const front = step * dx;
    const back = front + (rows - 1) * ROW_DX + width + extrudeX;
    return {
      step,
      x: front,
      width: back - front,
      y1: minY,
      y2: step * dy,
    };
  });

  return {
    viewBox: `${round(left)} ${round(top)} ${round(boxWidth)} ${round(boxHeight)}`,
    width: round(boxWidth),
    height: round(boxHeight),
    prisms,
    guides,
    labels,
    boundary,
    columns,
    rows,
    steps,
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
