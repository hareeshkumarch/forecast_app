"use client";

import { Activity, Info, TriangleAlert } from "lucide-react";

import { ErrorDistribution } from "@/components/charts/error-distribution";
import { ResidualTrend } from "@/components/charts/residual-trend";
import { metricLabel } from "@/components/diagnostics/metric-labels";
import { Badge, Card, EmptyState, ErrorState, PanelHeader, Skeleton } from "@/components/ui/primitives";
import { useForecastDiagnostics } from "@/hooks/use-dashboard";
import { formatCompact, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DiagnosticReport } from "@/types/api";

/** A metric is only a reading once it is in the shape its units expect. */
function render(name: string, value: number | null | undefined, currency: boolean): string {
  if (value === null || value === undefined) return "—";
  const { unit } = metricLabel(name);
  if (unit === "percent") return formatPercent(value);
  if (unit === "ratio") return value.toFixed(2);
  return formatCompact(value, currency);
}

function MetricTile({
  name,
  value,
  currency,
  lead,
}: {
  name: string;
  value: number | null | undefined;
  currency: boolean;
  lead: boolean;
}) {
  const label = metricLabel(name);
  return (
    <div
      className={cn(
        "border border-border bg-surface p-3",
        lead && "border-accent-border bg-accent-soft",
      )}
    >
      <p className="font-mono text-micro uppercase tracking-[0.08em] text-text-muted">
        {label.short}
      </p>
      <p
        className={cn(
          "mt-1 text-stat tabular-nums text-text-primary",
          lead && "text-accent",
        )}
      >
        {render(name, value, currency)}
      </p>
      {label.meaning ? (
        <p className="mt-1.5 text-caption leading-snug text-text-muted">{label.meaning}</p>
      ) : null}
    </div>
  );
}

/**
 * How a forecast is wrong, rather than how much.
 *
 * The scorecard answers the second question with one number. Two models can
 * share it and be broken in different ways: one loose in both directions, one
 * drifting steadily late. The residuals are where those separate, and the
 * metric set is chosen from the data rather than fixed — a series with zeros
 * in it is not shown a MAPE, and it is told why not.
 */
export function DiagnosticsPanel({
  runId,
  seriesId,
  currency = true,
}: {
  runId: string | null | undefined;
  seriesId?: string | null;
  currency?: boolean;
}) {
  const { data, isLoading, isError, refetch } = useForecastDiagnostics(runId, seriesId);

  if (isLoading) {
    return (
      <Card>
        <PanelHeader title="How this forecast is wrong" />
        <div className="grid gap-2 px-4 pb-4 sm:grid-cols-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
      </Card>
    );
  }

  if (isError || !data) {
    return (
      <Card>
        <PanelHeader title="How this forecast is wrong" />
        <ErrorState message="The diagnostics could not be loaded." onRetry={() => refetch()} />
      </Card>
    );
  }

  return <Report report={data} currency={currency} />;
}

function Report({ report, currency }: { report: DiagnosticReport; currency: boolean }) {
  const { plan, scored, residuals, histogram, residual_sigma: sigma, caveats } = report;
  const lead = plan.headline;
  const rest = plan.reported.filter((name) => name !== lead);

  return (
    <div className="grid gap-3">
      <Card>
        <PanelHeader
          title="What this series can be scored on"
          subtitle={plan.note}
          actions={<Badge tone="accent">{plan.demand_class.replace("_", " ")}</Badge>}
        />

        {residuals.length === 0 ? (
          <EmptyState
            icon={Info}
            title="Nothing scored yet"
            message={caveats[0] ?? "No period has both a forecast and an outcome against it."}
          />
        ) : (
          <div className="grid gap-2 px-4 pb-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricTile name={lead} value={scored[lead]} currency={currency} lead />
            {rest.map((name) => (
              <MetricTile
                key={name}
                name={name}
                value={scored[name]}
                currency={currency}
                lead={false}
              />
            ))}
          </div>
        )}

        {/* The withheld list is the point. "We did not show you MAPE" and
            "MAPE is undefined on a third of your weeks" are different
            messages, and only one of them is useful. */}
        {plan.withheld.length > 0 ? (
          <div className="border-t border-border px-4 py-3">
            <p className="flex items-center gap-1.5 font-mono text-micro uppercase tracking-[0.08em] text-text-muted">
              <TriangleAlert className="h-3 w-3" aria-hidden />
              Not shown for this data
            </p>
            <ul className="mt-2 grid gap-1.5">
              {plan.withheld.map((item) => (
                <li key={item.name} className="flex gap-2 text-caption text-text-secondary">
                  <span className="shrink-0 font-mono text-text-primary">
                    {metricLabel(item.name).short}
                  </span>
                  <span className="text-text-muted">{item.reason}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </Card>

      {residuals.length > 0 ? (
        <div className="grid gap-3 xl:grid-cols-2">
          <Card>
            <PanelHeader
              title="Where it missed"
              subtitle="Forecast minus actual, period by period. The band is one standard deviation."
            />
            <div className="px-2 pb-3">
              <ResidualTrend residuals={residuals} sigma={sigma} currency={currency} />
            </div>
          </Card>

          {histogram.length > 0 ? (
            <Card>
              <PanelHeader
                title="The shape of the error"
                subtitle="Weight on one side is a lean a planner can correct."
              />
              <div className="px-2 pb-3">
                <ErrorDistribution buckets={histogram} currency={currency} />
              </div>
            </Card>
          ) : (
            <Card>
              <PanelHeader title="The shape of the error" />
              <EmptyState
                icon={Activity}
                title="Too few periods to read a shape"
                message="A handful of residuals is a list, not a distribution."
              />
            </Card>
          )}
        </div>
      ) : null}

      {caveats.length > 0 && residuals.length > 0 ? (
        <p className="px-1 text-caption text-text-muted">{caveats.join(" ")}</p>
      ) : null}
    </div>
  );
}
