/**
 * Filter a date string (YYYY-MM-DD or ISO) by inclusive start/end.
 * Empty start/end means no bound.
 */
export function filterByDateRange(
  dateStr: string,
  start: string,
  end: string
): boolean {
  if (!dateStr) return true;
  const d = dateStr.slice(0, 10);
  const afterStart = start === "" || d >= start;
  const beforeEnd = end === "" || d <= end;
  return afterStart && beforeEnd;
}

/**
 * Take the last n elements. If n <= 0, return the whole array.
 */
export function takeLastN<T>(arr: T[], n: number): T[] {
  if (n <= 0 || arr.length <= n) return arr;
  return arr.slice(-n);
}

/**
 * Export best model forecast to CSV and trigger download.
 */
export function exportForecastCsv(
  bestModel: { forecast?: Array<{ date?: string; predicted?: number; lower?: number; upper?: number }> },
  jobId: string
): void {
  const forecast = bestModel.forecast || [];
  const rows = [
    ["Date", "Predicted", "Lower", "Upper"],
    ...forecast.map((f) => [
      f.date?.slice(0, 10) ?? "",
      f.predicted?.toFixed(2) ?? "",
      f.lower?.toFixed(2) ?? "",
      f.upper?.toFixed(2) ?? "",
    ]),
  ];
  const csv = rows.map((r) => r.join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `forecast_${jobId}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}
