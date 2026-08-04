"use client";


import { Globe2 } from "lucide-react";

import { AccuracyCell } from "@/components/dashboard/accuracy-cell";
import { Card, EmptyState, ErrorState, PanelHeader, Skeleton } from "@/components/ui/primitives";
import { SortableHeader, useSortedRows } from "@/components/ui/sortable-header";
import { useRegions } from "@/hooks/use-dashboard";
import type { RegionRow } from "@/types/api";
import { formatCompact, formatSignedPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

type RegionSortKey = "region" | "forecast_value" | "change_vs_last_year" | "accuracy";

export function RegionTable() {
  const { data, isLoading, isError, error, refetch } = useRegions();

  const { sorted, sort, toggle } = useSortedRows<RegionRow, RegionSortKey>(
    data?.rows ?? [],
    { key: "forecast_value", direction: "desc" },
    (row, key) => row[key],
  );

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
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : data && data.rows.length > 0 ? (
          
          
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full min-w-[420px] border-collapse">
              <thead>
                <tr className="border-b border-border">
                  <SortableHeader label="Region" sortKey="region" sort={sort} onToggle={toggle} className="text-left" />
                  <SortableHeader label="Forecast" sortKey="forecast_value" sort={sort} onToggle={toggle} align="right" className="text-right" />
                  <SortableHeader label="vs LY" sortKey="change_vs_last_year" sort={sort} onToggle={toggle} align="right" className="text-right" />
                  <SortableHeader label="Accuracy" sortKey="accuracy" sort={sort} onToggle={toggle} align="right" className="text-right" />
                </tr>
              </thead>
              <tbody>
                {sorted.map((row) => (
                  <tr
                    key={row.region}
                    className="border-b border-border last:border-0 transition-colors duration-fast hover:bg-surface-muted"
                  >
                    <td className="cell px-3 text-meta text-text-primary">{row.region}</td>
                    <td className="cell px-3 text-right text-meta font-semibold text-text-primary num">
                      {formatCompact(row.forecast_value)}
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
                    <td className="cell px-3 text-right text-meta">
                      <AccuracyCell
                        value={row.accuracy}
                        measured={row.accuracy_measured}
                        model={row.model}
                      />
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
