export type Align = "start" | "end";

export type Column = {
  key: string;
  head: string;
  width: number;
  align: Align;
  role?: "date" | "value";
};

export const COLUMNS: Column[] = [
  { key: "week", head: "week_start", width: 150, align: "start", role: "date" },
  { key: "sku", head: "sku", width: 130, align: "start" },
  { key: "units", head: "units_sold", width: 124, align: "end", role: "value" },
  { key: "price", head: "unit_price", width: 116, align: "end" },
];

export const SOLD = [412, 468, 395, 501, 447, 523, 486];

export const AHEAD = [455, 512, 470, 528, 495, 540];

function monday(index: number): string {
  const date = new Date(Date.UTC(2024, 7, 5));
  date.setUTCDate(date.getUTCDate() + index * 7);
  return date.toISOString().slice(0, 10);
}

export const ROWS = SOLD.map((units, index) => ({
  week: monday(index),
  sku: `CH-22${10 + index}`,
  units: String(units),
  price: (4.1 + index * 0.05).toFixed(2),
}));

const SPREAD_BASE = 0.045;
const SPREAD_STEP = 0.023;

export function spread(step: number): number {
  return SPREAD_BASE + SPREAD_STEP * step;
}

export const STAGE = {
  width: 520,
  height: 400,
  headTop: 4,
  headHeight: 28,
  rowTop: 44,
  rowHeight: 38,
  cellHeight: 30,
  baseline: 350,
  barWidth: 26,
  ceiling: 280,
} as const;

export const SLOTS = SOLD.length + AHEAD.length;

const PEAK = Math.max(...AHEAD.map((value, step) => value * (1 + spread(step))), ...SOLD);

export function lift(value: number): number {
  return (value / PEAK) * STAGE.ceiling;
}

export function columnX(index: number): number {
  return COLUMNS.slice(0, index).reduce((sum, column) => sum + column.width, 0);
}

export function rowY(index: number): number {
  return STAGE.rowTop + index * STAGE.rowHeight;
}

export function slotWidth(): number {
  return STAGE.width / SLOTS;
}

export function slotX(index: number): number {
  return index * slotWidth() + (slotWidth() - STAGE.barWidth) / 2;
}

export type Morph = {
  dx: number;
  dy: number;
  sx: number;
  sy: number;
  height: number;
};

export function morph(index: number): Morph {
  const column = COLUMNS.findIndex((entry) => entry.role === "value");
  const from = { x: columnX(column), y: rowY(index) + STAGE.cellHeight, w: COLUMNS[column]?.width ?? 1 };
  const height = lift(SOLD[index] ?? 0);

  return {
    dx: slotX(index) - from.x,
    dy: STAGE.baseline - from.y,
    sx: STAGE.barWidth / from.w,
    sy: height / STAGE.cellHeight,
    height,
  };
}

export type Beats = {
  fill: number;
  read: number;
  build: number;
  ahead: number;
};

const FILL_END = 0.3;
const READ_END = 0.63;
const AHEAD_START = 0.78;

const HOLD = 0.14;

export function clamp01(value: number): number {
  return Math.min(Math.max(value, 0), 1);
}

export function ease(value: number): number {
  return 1 - (1 - clamp01(value)) ** 2;
}

export function beats(progress: number): Beats {
  const p = clamp01(progress / (1 - HOLD));
  return {
    fill: clamp01(p / FILL_END),
    read: clamp01((p - FILL_END) / (READ_END - FILL_END)),
    build: ease((p - READ_END) / (1 - READ_END)),
    ahead: ease((p - AHEAD_START) / (1 - AHEAD_START)),
  };
}

export function activeStep(progress: number): number {
  const p = clamp01(progress / (1 - HOLD));
  if (p < FILL_END) return 0;
  if (p < READ_END) return 1;
  return 2;
}
