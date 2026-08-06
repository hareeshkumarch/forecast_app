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

/**
 * How many periods make a year at this frequency.
 *
 * "Last year" has to mean 365 days on a daily run and four periods on a
 * quarterly one; a fixed count would quietly mean something different for
 * every dataset.
 */
export function periodsPerYear(frequency: ForecastFrequency | null | undefined): number {
  switch (frequency) {
    case "daily":
      return 365;
    case "weekly":
      return 52;
    case "quarterly":
      return 4;
    case "monthly":
    default:
      return 12;
  }
}

//: What one step of each frequency is called, so a lead can be described in
//: the reader's own units rather than as "6 periods".
const PERIOD_WORDS: Record<ForecastFrequency, [string, string]> = {
  daily: ["day", "days"],
  weekly: ["week", "weeks"],
  monthly: ["month", "months"],
  quarterly: ["quarter", "quarters"],
};

/** "6 months earlier", for a lead of six periods on a monthly run. */
export function periodsAgo(
  periods: number,
  frequency: ForecastFrequency | null | undefined,
): string {
  const [singular, plural] = PERIOD_WORDS[frequency ?? "monthly"] ?? ["period", "periods"];
  return `${periods} ${periods === 1 ? singular : plural} earlier`;
}
