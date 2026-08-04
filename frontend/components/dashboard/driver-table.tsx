"use client";


import { Card, ErrorState, PanelHeader, Skeleton } from "@/components/ui/primitives";
import { Sparkline } from "@/components/dashboard/sparkline";
import { useDrivers } from "@/hooks/use-dashboard";
import { formatCompact, formatSignedPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

export function DriverTable() {
  const { data, isLoading, isError, error, refetch } = useDrivers();

  return (
    <Card className="flex min-w-0 flex-col">
      <PanelHeader
        title="Top Drivers Impacting Forecast"
        subtitle="Decomposed contribution to forecast movement"
      />

      <div className="min-h-0 flex-1 px-1 pb-2">
        {isLoading ? (
          <div className="space-y-2 px-3 py-2" aria-hidden>
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-6 w-full" />
            ))}
          </div>
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => void refetch()} />
        ) : data && data.rows.length > 0 ? (
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full min-w-[440px] border-collapse">
              <thead>
                <tr className="border-b border-border">
                  <th className="table-header px-3 pb-1.5 text-left font-medium">Driver</th>
                  <th className="table-header px-3 pb-1.5 text-right font-medium">Impact</th>
                  <th className="table-header px-3 pb-1.5 text-right font-medium">vs LY</th>
                  <th className="table-header px-3 pb-1.5 text-right font-medium">Trend</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr
                    key={row.driver}
                    className="border-b border-border last:border-0 transition-colors duration-fast hover:bg-surface-muted"
                  >
                    <td className="px-3 py-[9px] text-meta text-text-primary">
                      {row.driver}
                      <span className="ml-1.5 text-caption text-text-muted num">
                        {row.impact_pct >= 0 ? "+" : ""}
                        {row.impact_pct.toFixed(1)}%
                      </span>
                    </td>
                    <td
                      className={cn(
                        "px-3 py-[9px] text-right text-meta font-semibold num",
                        row.impact_value >= 0 ? "text-text-primary" : "text-negative",
                      )}
                    >
                      {formatCompact(row.impact_value)}
                    </td>
                    <td
                      className={cn(
                        "px-3 py-[9px] text-right text-meta font-medium num",
                        row.change_vs_last_year === null
                          ? "text-text-muted"
                          : row.change_vs_last_year >= 0
                            ? "text-positive"
                            : "text-negative",
                      )}
                    >
                      {formatSignedPercent(row.change_vs_last_year)}
                    </td>
                    <td className="px-3 py-[7px]">
                      <div className="flex justify-end">
                        <Sparkline values={row.trend} direction={row.direction} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex h-[180px] items-center justify-center px-4">
            <p className="text-center text-caption text-text-muted">
              Driver decomposition needs a completed forecast run.
            </p>
          </div>
        )}
      </div>
    </Card>
  );
}
