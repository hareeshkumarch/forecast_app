/**
 * Timing for the accuracy diagram.
 *
 * The diagram makes a three-step argument — here is your history, here are the
 * weeks we held back, here is what we said about them — and the motion tells
 * it in the same three steps. Rising all sixty bars on one clock says only
 * "something appeared"; it does not say which part the reader is meant to
 * compare against which.
 */

/** A bar rising to its value. Never past it: these encode real numbers. */
export const BAR_RISE = 340;

/** A held-back week fading in as a dashed outline. */
export const GHOST_FADE = 220;

/** The rule marking what the week actually came to. */
export const TICK_DRAW = 200;

/** Bars march left to right at a steady pace. */
export const BAR_STAGGER = 12;

/** The held-back weeks march more slowly, because they are the point. */
export const HELD_STAGGER = 28;

/**
 * A row starts before the one above it has settled. Three clean waits would
 * read as three separate animations; this reads as one argument with three
 * beats in it.
 */
export const ROW_ADVANCE = 260;

/** The gap that turns "these weeks" into "…and then these ones". */
export const HELD_GAP = 150;

/** The outcome rule lands on a bar that has already mostly risen. */
export const TICK_GAP = 280;

/** What the whole diagram must settle within. Asserted by the tests. */
export const CHECK_BUDGET = 1600;

/**
 * `bar` is a week whose sales were never hidden, `held` a week that was, and
 * `tick` the rule showing what a held week actually came to.
 */
export type Mark = "bar" | "held" | "tick";

export function checkDelay(row: number, index: number, shown: number, mark: Mark): number {
  const base = row * ROW_ADVANCE;
  if (mark === "bar") return base + index * BAR_STAGGER;

  // The held weeks start from where the shown ones finished, so the two groups
  // read as one row continuing rather than two rows overlapping.
  const held = base + shown * BAR_STAGGER + HELD_GAP + (index - shown) * HELD_STAGGER;
  return mark === "tick" ? held + TICK_GAP : held;
}

export function checkSettled(rows: number, total: number, shown: number): number {
  const last = rows - 1;
  const lastHeld = total - 1;
  return Math.max(
    checkDelay(last, shown - 1, shown, "bar") + BAR_RISE,
    checkDelay(last, lastHeld, shown, "held") + Math.max(BAR_RISE, GHOST_FADE),
    checkDelay(last, lastHeld, shown, "tick") + TICK_DRAW,
  );
}
