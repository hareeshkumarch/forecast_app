let currencySymbol = "$";

export function setCurrencySymbol(symbol: string): void {
  currencySymbol = symbol || "$";
}

const SCALES: [number, string, number][] = [
  [1e12, "T", 2],
  [1e9, "B", 2],
  [1e6, "M", 2],
  [1e3, "K", 1],
];

const EXPONENT_BELOW = 1e-4;

const SIGNIFICANT = 3;

export function formatCompact(value: number | null | undefined, currency = true): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";

  const prefix = currency ? currencySymbol : "";
  const sign = value < 0 ? "-" : "";
  const magnitude = Math.abs(value);

  for (const [threshold, suffix, digits] of SCALES) {
    if (magnitude >= threshold) {
      return `${sign}${prefix}${(magnitude / threshold).toFixed(digits)}${suffix}`;
    }
  }

  if (magnitude >= 1) {
    return `${sign}${prefix}${magnitude.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  }
  if (magnitude === 0) return `${prefix}0`;
  if (magnitude < EXPONENT_BELOW) {
    return `${sign}${prefix}${magnitude.toExponential(SIGNIFICANT - 1)}`;
  }

  const places = SIGNIFICANT - 1 - Math.floor(Math.log10(magnitude));
  const trimmed = magnitude.toFixed(places).replace(/\.?0+$/, "");
  return `${sign}${prefix}${trimmed}`;
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

export function formatSignedPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function formatInteger(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

export function formatMonth(iso: string): string {
  const date = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return date.toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
}

export function formatDayMonth(iso: string): string {
  const date = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

export function formatDateRange(
  start: string | null,
  end: string | null,
  granularity: "day" | "month" = "month",
): string {
  if (!start || !end) return "All dates";
  const format = granularity === "day" ? formatDayMonth : formatMonth;
  return `${format(start)} – ${format(end)}`;
}

export function formatRelativeTime(iso: string | null): string {
  if (!iso) return "—";

  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";

  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function humanizeKey(key: string): string {
  const spaced = key.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function humanizeModel(model: string | null | undefined): string {
  if (!model) return "—";
  return model
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function formatMetric(value: number, unit: string, currency = true): string {
  switch (unit) {
    case "percent":
      return formatPercent(value);
    case "percentage_points":
      return `${value >= 0 ? "+" : ""}${value.toFixed(1)}pp`;
    case "count":
      return formatInteger(value);
    case "ratio":
      return `${value.toFixed(2)}x`;
    case "std_dev":
      return `${value.toFixed(1)}σ`;
    default:
      return formatCompact(value, currency);
  }
}
