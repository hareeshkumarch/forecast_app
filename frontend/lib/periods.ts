import type { ForecastFrequency } from "@/types/api";

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

export function periodWindowEnd(
  start: string,
  count: number,
  frequency: ForecastFrequency,
): string {
  return addPeriods(start, Math.max(count - 1, 0), frequency);
}

export function labelGranularity(frequency: ForecastFrequency | null | undefined): "day" | "month" {
  return frequency === "daily" || frequency === "weekly" ? "day" : "month";
}

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

const PERIOD_WORDS: Record<ForecastFrequency, [string, string]> = {
  daily: ["day", "days"],
  weekly: ["week", "weeks"],
  monthly: ["month", "months"],
  quarterly: ["quarter", "quarters"],
};

export function periodWord(
  frequency: ForecastFrequency | null | undefined,
  count: number,
): string {
  const [singular, plural] = PERIOD_WORDS[frequency ?? "monthly"] ?? ["period", "periods"];
  return count === 1 ? singular : plural;
}

export function periodsAgo(
  periods: number,
  frequency: ForecastFrequency | null | undefined,
): string {
  return `${periods} ${periodWord(frequency, periods)} earlier`;
}
