"use client";

import { AlertTriangle, CheckCircle2, Info, Loader2, ShieldAlert } from "lucide-react";

import { errorMessage } from "@/lib/errors";
import { formatInteger } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DataQualityResponse, IssueSeverity } from "@/types/api";

const SEVERITY = {
  severe: {
    icon: ShieldAlert,
    text: "text-negative",
    border: "border-negative-border",
    background: "bg-negative-soft",
    label: "Blocked",
  },
  warning: {
    icon: AlertTriangle,
    text: "text-warning",
    border: "border-warning-border",
    background: "bg-warning-soft",
    label: "Check first",
  },
  info: {
    icon: Info,
    text: "text-text-secondary",
    border: "border-border",
    background: "bg-surface-muted",
    label: "For information",
  },
} as const satisfies Record<IssueSeverity, unknown>;

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-chip border border-border bg-surface px-2 py-1.5">
      <p className="truncate text-caption text-text-muted">{label}</p>
      <p className={cn("mt-0.5 text-meta font-semibold num", tone ?? "text-text-primary")}>
        {value}
      </p>
    </div>
  );
}

export function DataQualityPanel({
  report,
  isLoading,
  error,
}: {
  report: DataQualityResponse | undefined;
  isLoading: boolean;
  error: unknown;
}) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-card border border-border bg-surface-muted px-3 py-2.5">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-text-muted" aria-hidden />
        <p className="text-caption text-text-secondary">Checking the data…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-start gap-2 rounded-card border border-warning-border bg-warning-soft px-3 py-2.5">
        <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
        <p className="text-caption text-warning">{errorMessage(error)}</p>
      </div>
    );
  }

  if (!report) return null;

  const tone = SEVERITY[report.severity];
  const ToneIcon = report.issues.length === 0 ? CheckCircle2 : tone.icon;
  const coverage = Math.round(report.coverage * 100);

  return (
    <section
      aria-label="Data quality"
      className={cn("rounded-card border", tone.border, tone.background, "px-3 py-2.5")}
    >
      <div className="flex flex-wrap items-center gap-2">
        <ToneIcon
          className={cn(
            "h-4 w-4 shrink-0",
            report.issues.length === 0 ? "text-positive" : tone.text,
          )}
          aria-hidden
        />
        <p className="text-body font-medium text-text-primary">
          {report.issues.length === 0
            ? "This series looks clean"
            : report.blocked
              ? "This series cannot be forecast yet"
              : `${report.issues.length} thing${report.issues.length === 1 ? "" : "s"} to know`}
        </p>
        <span className="ml-auto text-caption text-text-muted num">
          {formatInteger(report.periods_present)} of {formatInteger(report.periods_expected)} periods
        </span>
      </div>

      <div
        className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface"
        role="meter"
        aria-valuenow={coverage}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Calendar coverage"
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-300",
            coverage >= 95 ? "bg-positive" : coverage >= 70 ? "bg-warning" : "bg-negative",
          )}
          style={{ width: `${Math.max(coverage, 2)}%` }}
        />
      </div>

      <div className="mt-2.5 grid grid-cols-2 gap-1.5 sm:grid-cols-4">
        <Stat label="Coverage" value={`${coverage}%`} />
        <Stat
          label="Gaps"
          value={formatInteger(report.gap_count)}
          tone={report.gap_count > 0 ? "text-warning" : undefined}
        />
        <Stat label="Rows used" value={formatInteger(report.rows_usable)} />
        <Stat
          label="Outliers"
          value={formatInteger(report.outlier_periods)}
          tone={report.outlier_periods > 0 ? "text-warning" : undefined}
        />
      </div>

      {report.issues.length > 0 ? (
        <ul className="mt-2.5 space-y-1.5">
          {report.issues.map((issue) => {
            const style = SEVERITY[issue.severity];
            const Icon = style.icon;

            return (
              <li key={issue.code} className="flex items-start gap-2">
                <Icon className={cn("mt-px h-3 w-3 shrink-0", style.text)} aria-hidden />
                <div className="min-w-0">
                  <p className="text-caption font-medium text-text-primary">{issue.message}</p>
                  <p className="text-caption text-text-muted">{issue.remedy}</p>
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}

      {report.gap_count > 0 && !report.blocked ? (
        <p className="mt-2 text-caption text-text-muted">
          Missing periods are filled by{" "}
          <span className="font-medium text-text-secondary">{report.fill_applied}</span> so the
          calendar stays regular — without it the series would be squashed and the forecast skewed.
        </p>
      ) : null}
    </section>
  );
}
