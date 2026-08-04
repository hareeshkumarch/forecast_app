"use client";


import { Activity } from "lucide-react";

import { Card, EmptyState, ErrorState, PanelHeader, Skeleton } from "@/components/ui/primitives";
import { SortableHeader, useSortedRows } from "@/components/ui/sortable-header";
import { Sparkline } from "@/components/dashboard/sparkline";
import { useDrivers } from "@/hooks/use-dashboard";
import type { DriverRow } from "@/types/api";
import { formatCompact, formatSignedPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

type DriverSortKey = "driver" | "impact_value" | "change_vs_last_year";

export function DriverTable() {
  const { data, isLoading, isError, error, refetch } = useDrivers();

  const { sorted, sort, toggle } = useSortedRows<DriverRow, DriverSortKey>(
    data?.rows ?? [],
    { key: "impact_value", direction: "desc" },
    (row, key) => row[key],
  );

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
                  <SortableHeader label="Driver" sortKey="driver" sort={sort} onToggle={toggle} className="text-left" />
                  <SortableHeader label="Impact" sortKey="impact_value" sort={sort} onToggle={toggle} align="right" className="text-right" />
                  <SortableHeader label="vs LY" sortKey="change_vs_last_year" sort={sort} onToggle={toggle} align="right" className="text-right" />
                  <th className="table-header px-3 pb-1.5 text-right font-medium">Trend</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((row) => (
                  <tr
                    key={row.driver}
                    className="border-b border-border last:border-0 transition-colors duration-fast hover:bg-surface-muted"
                  >
                    <td className="cell px-3 text-meta text-text-primary">
                      {row.driver}
                      <span className="ml-1.5 text-caption text-text-muted num">
                        {row.impact_pct >= 0 ? "+" : ""}
                        {row.impact_pct.toFixed(1)}%
                      </span>
                    </td>
                    <td
                      className={cn(
                        "cell px-3 text-right text-meta font-semibold num",
                        row.impact_value >= 0 ? "text-text-primary" : "text-negative",
                      )}
                    >
                      {formatCompact(row.impact_value)}
                    </td>
                    <td
                      className={cn(
                        "cell px-3 text-right text-meta font-medium num",
                        row.change_vs_last_year === null
                          ? "text-text-muted"
                          : row.change_vs_last_year >= 0
                            ? "text-positive"
                            : "text-negative",
                      )}
                    >
                      {formatSignedPercent(row.change_vs_last_year)}
                    </td>
                    <td className="cell px-3">
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
          <EmptyState
            icon={Activity}
            title="No drivers yet"
            message="Driver decomposition needs a completed forecast run."
          />
        )}
      </div>
    </Card>
  );
}
