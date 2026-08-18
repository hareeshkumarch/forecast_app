/**
 * Timing for the planning band.
 *
 * The track opens first and the three figures land on it left to right, so a
 * range is established before anything is placed inside it. Landing all three
 * at once reads as a row of statistics rather than three positions on a scale.
 */

export const BAND_GROW = 560;
export const MARK_LAND = 300;
export const FIRST_MARK = 300;
export const MARK_STAGGER = 120;

/** What the whole band must settle within. Asserted by the tests. */
export const PLAN_BUDGET = 1100;

export function markDelay(index: number): number {
  return FIRST_MARK + index * MARK_STAGGER;
}

export function planSettled(marks: number): number {
  return Math.max(BAND_GROW + MARK_LAND, markDelay(marks - 1) + MARK_LAND);
}
