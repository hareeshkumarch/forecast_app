import type { ForecastFrequency } from "@/types/api";

/**
 * Date arithmetic in the unit the run was actually fitted at. A "next 6
 * periods" preset means six days on a daily run and six quarters on a
 * quarterly one — stepping by months regardless would silently mislabel it.
 */
export function addPeriods(iso: string, periods: number, frequency: ForecastFrequency): string {
  const date = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return iso.slice(0, 10);

  switch (frequency) {
    case "daily":
      date.setUTCDate(date.getUTCDate() + periods);
      break;
    case "weekly":
      date.setUTCDate(date.getUTCDate() + periods * 7);
      break;
    case "quarterly":
      date.setUTCMonth(date.getUTCMonth() + periods * 3);
      break;
    case "monthly":
    default:
      date.setUTCMonth(date.getUTCMonth() + periods);
      break;
  }

  return date.toISOString().slice(0, 10);
}

/** Inclusive window: `count` periods starting at (and including) `start`. */
export function periodWindowEnd(
  start: string,
  count: number,
  frequency: ForecastFrequency,
): string {
  return addPeriods(start, Math.max(count - 1, 0), frequency);
}

/** Daily and weekly runs need day precision in labels; coarser ones do not. */
export function labelGranularity(frequency: ForecastFrequency | null | undefined): "day" | "month" {
  return frequency === "daily" || frequency === "weekly" ? "day" : "month";
}
