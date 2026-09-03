/**
 * The build the "how it works" section scrubs through as it is scrolled.
 *
 * The section used to say the three steps and show nothing: a column of prose
 * with the other half of the page empty beside it. Words are the wrong tool
 * for "we work out which column holds the date" — it is a thing to be watched
 * happening, and watching it costs the reader no sentences at all.
 *
 * So the same seven numbers are followed the whole way through. They arrive as
 * rows of a spreadsheet, two columns are picked out of them, and then the
 * quantity column's own cells travel down and become the bars of a forecast.
 * Nothing is swapped for a different picture at any point, which is what makes
 * it read as one process rather than three illustrations.
 *
 * Geometry only. What moves it is the scroll position, and that lives in
 * `components/marketing/scroll-stage.tsx`.
 */

export type Align = "start" | "end";

export type Column = {
  key: string;
  head: string;
  width: number;
  align: Align;
  /** The two the second beat picks out. */
  role?: "date" | "value";
};

/*
 * Four columns, not the six a real export has. Two of them are the ones the
 * second beat picks out and two are there to be passed over, which is the
 * whole of what the beat has to show — and every column past that is one more
 * thing set at a third of its size on a phone, where the sheet has 340px to
 * be legible in.
 */
export const COLUMNS: Column[] = [
  { key: "week", head: "week_start", width: 150, align: "start", role: "date" },
  { key: "sku", head: "sku", width: 130, align: "start" },
  { key: "units", head: "units_sold", width: 124, align: "end", role: "value" },
  { key: "price", head: "unit_price", width: 116, align: "end" },
];

/** What the quantity column holds, and therefore what the bars are. */
export const SOLD = [412, 468, 395, 501, 447, 523, 486];

export const AHEAD = [455, 512, 470, 528, 495, 540];

/** Consecutive Mondays, rolled over the month end rather than counted past
 *  it — a sheet showing `2024-08-33` is a sheet nobody believes. */
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

/**
 * How far the range opens. It has to widen with the horizon — a band of
 * constant width is the same false confidence as no band at all, drawn
 * slightly differently.
 */
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
  /** The tallest mark the chart can draw, band included. */
  ceiling: 280,
} as const;

export const SLOTS = SOLD.length + AHEAD.length;

const PEAK = Math.max(...AHEAD.map((value, step) => value * (1 + spread(step))), ...SOLD);

/** Values to pixels. One scale for both halves, or the forecast would be a
 *  claim drawn at a different size from the history it follows. */
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
  /** How far the cell travels to reach the bar it becomes. */
  dx: number;
  dy: number;
  /** And what it has to become on the way. Origin is the bottom-left corner. */
  sx: number;
  sy: number;
  height: number;
};

/**
 * A quantity cell, and the bar it turns into.
 *
 * Expressed as an offset and a scale rather than as a second set of
 * coordinates, so the whole journey is one CSS transform interpolated by a
 * single custom property — the browser moves the cell, and nothing re-renders
 * on the way.
 */
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
  /** Rows landing in the sheet. */
  fill: number;
  /** The two columns being picked out. */
  read: number;
  /** The quantity column leaving the sheet and becoming the history. */
  build: number;
  /** The forecast and its range drawing ahead of it. */
  ahead: number;
};

/* Where one beat hands over to the next. The build starts before the read has
   quite finished, so the section never sits still between two of them. */
const FILL_END = 0.3;
const READ_END = 0.63;
const AHEAD_START = 0.78;

/* The last of the travel holds the finished chart. Without it the forecast
   completes on the frame the pin lets go, and the one picture the section is
   built to arrive at is the one nobody gets to look at. */
const HOLD = 0.14;

export function clamp01(value: number): number {
  return Math.min(Math.max(value, 0), 1);
}

/** Quick to leave, slow to arrive — a scrub that eased in as well would feel
 *  like it was lagging the scroll that drives it. */
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

/** Which of the three steps the scroll is currently inside. */
export function activeStep(progress: number): number {
  const p = clamp01(progress / (1 - HOLD));
  if (p < FILL_END) return 0;
  if (p < READ_END) return 1;
  return 2;
}
