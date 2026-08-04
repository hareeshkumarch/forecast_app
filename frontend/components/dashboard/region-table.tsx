"use client";


import { Globe2 } from "lucide-react";

import { Card, EmptyState, ErrorState, PanelHeader, Skeleton } from "@/components/ui/primitives";
import { useRegions } from "@/hooks/use-dashboard";
import { formatCompact, formatPercent, formatSignedPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

export function RegionTable() {
  const { data, isLoading, isError, error, refetch } = useRegions();

  return (
    <Card className="flex min-w-0 flex-col">
      <PanelHeader title="Forecast by Region" subtitle="Next horizon, by geography" />

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
            <table className="w-full min-w-[420px] border-collapse">
              <thead>
                <tr className="border-b border-border">
                  <th className="table-header px-3 pb-1.5 text-left font-medium">Region</th>
                  <th className="table-header px-3 pb-1.5 text-right font-medium">Forecast</th>
                  <th className="table-header px-3 pb-1.5 text-right font-medium">vs LY</th>
                  <th className="table-header px-3 pb-1.5 text-right font-medium">Accuracy</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr
                    key={row.region}
                    className="border-b border-border last:border-0 transition-colors duration-fast hover:bg-surface-muted"
                  >
                    <td className="px-3 py-[9px] text-meta text-text-primary">{row.region}</td>
                    <td className="px-3 py-[9px] text-right text-meta font-semibold text-text-primary num">
                      {formatCompact(row.forecast_value)}
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
                    <td className="px-3 py-[9px] text-right text-meta text-text-secondary num">
                      {formatPercent(row.accuracy)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-border-strong">
                  <td className="px-3 pt-2 text-caption font-medium text-text-muted">Total</td>
                  <td className="px-3 pt-2 text-right text-meta font-semibold text-text-primary num">
                    {formatCompact(data.total)}
                  </td>
                  <td colSpan={2} />
                </tr>
              </tfoot>
            </table>
          </div>
        ) : (
          <EmptyState
            icon={Globe2}
            title="No regional breakdown"
            message="Map a region column when you run a forecast to split it by geography."
          />
        )}
      </div>
    </Card>
  );
}
