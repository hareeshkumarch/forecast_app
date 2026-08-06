"use client";

import { Activity, Clock3, Coins, Cpu, Send, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { EChart, type ChartOption } from "@/components/charts/echart";
import { Badge, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { RefreshButton } from "@/components/ui/refresh-button";
import { Select } from "@/components/ui/select";
import { useLlmUsage } from "@/hooks/use-dashboard";
import { axisLabel, axisLine, chartColors, splitLine, tooltipStyle } from "@/lib/chart-theme";
import { useThemeRevision } from "@/stores/prefs-store";
import type { LlmUsageResponse } from "@/types/api";

const WINDOWS = [
  { value: "7", label: "Last 7 days", days: 7 },
  { value: "30", label: "Last 30 days", days: 30 },
  { value: "90", label: "Last 90 days", days: 90 },
];

function compact(value: number): string {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function cost(value: number, priced: number, requests: number): string {
  if (requests > 0 && priced === 0) return "Not priced";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function latency(value: number | null): string {
  if (value === null) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(2)}s` : `${Math.round(value)}ms`;
}

function MetricCard({ label, value, hint, icon: Icon }: { label: string; value: string; hint: string; icon: typeof Activity }) {
  return (
    <Card className="p-3.5">
      <span className="flex h-7 w-7 items-center justify-center rounded-[7px] bg-surface-muted">
        <Icon className="h-3.5 w-3.5 text-text-muted" aria-hidden />
      </span>
      <p className="mt-3 text-caption text-text-muted">{label}</p>
      <p className="mt-0.5 text-kpi font-semibold tracking-[-0.02em] text-text-primary num">{value}</p>
      <p className="mt-1 text-caption text-text-muted">{hint}</p>
    </Card>
  );
}

function buildTrendOption(data: LlmUsageResponse): ChartOption {
  const colors = chartColors();
  const labels = data.timeseries.map((point) => point.date.slice(5));
  return {
    backgroundColor: "transparent",
    animation: false,
    grid: { left: 8, right: 8, top: 22, bottom: 4, containLabel: true },
    tooltip: { ...tooltipStyle(colors), trigger: "axis", confine: true },
    legend: {
      top: 0,
      left: 0,
      itemWidth: 14,
      itemHeight: 2,
      textStyle: { ...axisLabel(colors), color: colors.textSecondary },
      data: ["Tokens", "Requests"],
    },
    xAxis: {
      type: "category",
      data: labels,
      boundaryGap: false,
      axisLine: axisLine(colors),
      axisTick: { show: false },
      axisLabel: { ...axisLabel(colors), hideOverlap: true, margin: 10 },
    },
    yAxis: [
      {
        type: "value",
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { ...axisLabel(colors), formatter: (value: number) => compact(value) },
        splitLine: splitLine(colors),
      },
      {
        type: "value",
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { ...axisLabel(colors) },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: "Tokens",
        type: "line",
        data: data.timeseries.map((point) => point.total_tokens),
        showSymbol: false,
        smooth: 0.18,
        lineStyle: { color: colors.navy, width: 2 },
        areaStyle: { color: colors.navy, opacity: 0.08 },
      },
      {
        name: "Requests",
        type: "line",
        yAxisIndex: 1,
        data: data.timeseries.map((point) => point.requests),
        showSymbol: false,
        lineStyle: { color: colors.accent, width: 2, type: "dashed" },
      },
    ],
  };
}

function SectionTitle({ title, subtitle, actions }: { title: string; subtitle: string; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border px-4 py-3.5">
      <div>
        <h2 className="panel-title">{title}</h2>
        <p className="mt-0.5 text-caption text-text-muted">{subtitle}</p>
      </div>
      {actions}
    </div>
  );
}

export function UsageWorkspace() {
  const [days, setDays] = useState<number | null>(null);
  const { data, isLoading, isError, error, refetch, isFetching, dataUpdatedAt } =
    useLlmUsage(days ?? WINDOWS[0]!.days);

  useEffect(() => {
    if (days !== null || !data) return;
    const first = data.first_event_at ? new Date(data.first_event_at).getTime() : null;
    if (first === null || Number.isNaN(first)) {
      setDays(WINDOWS[0]!.days);
      return;
    }
    const elapsed = Math.ceil((Date.now() - first) / 86_400_000) + 1;
    setDays(WINDOWS.find((window) => window.days >= elapsed)?.days ?? WINDOWS.at(-1)!.days);
  }, [data, days]);
  const revision = useThemeRevision();
  const option = useMemo(() => {
    void revision;
    return data ? buildTrendOption(data) : null;
  }, [data, revision]);
  const totals = data?.totals;
  const successRate = totals?.requests ? (totals.successful_requests / totals.requests) * 100 : 0;

  return (
    <main id="main-content" className="scroll-thin min-w-0 flex-1 overflow-y-auto bg-canvas px-4 py-4 sm:px-6 sm:py-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-heading font-semibold tracking-[-0.015em] text-text-primary">LLM Usage</h1>
          <p className="mt-0.5 text-meta text-text-secondary">
            Request outcomes, tokens, latency, and cost for AI-assisted insight rewriting.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select
            label="Usage window"
            value={String(days ?? WINDOWS[0]!.days)}
            onChange={(next) => setDays(Number(next))}
            options={WINDOWS}
            className="w-[152px]"
          />
          <RefreshButton
            updatedAt={dataUpdatedAt}
            isFetching={isFetching}
            onRefresh={() => void refetch()}
          />
        </div>
      </div>

      {isLoading ? (
        <div className="mt-4 space-y-3" aria-hidden>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
            {Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="h-36 w-full" />)}
          </div>
          <Skeleton className="h-72 w-full" />
        </div>
      ) : isError ? (
        <Card className="mt-4"><ErrorState error={error} onRetry={() => void refetch()} /></Card>
      ) : data && totals ? (
        <>
          <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-3 2xl:grid-cols-6">
            <MetricCard label="Requests" value={compact(totals.requests)} hint={`${days}-day window`} icon={Send} />
            <MetricCard label="Total tokens" value={compact(totals.total_tokens)} hint={`${compact(totals.input_tokens)} in · ${compact(totals.output_tokens)} out`} icon={Cpu} />
            <MetricCard label="Cost" value={cost(totals.cost_usd, totals.priced_requests, totals.requests)} hint={`${totals.priced_requests} priced requests`} icon={Coins} />
            <MetricCard label="Success rate" value={`${successRate.toFixed(1)}%`} hint={`${totals.failed_requests} failed · ${totals.rejected_requests} rejected`} icon={Activity} />
            <MetricCard label="Average latency" value={latency(totals.average_latency_ms)} hint="Provider round trip" icon={Clock3} />
            <MetricCard label="P95 latency" value={latency(totals.p95_latency_ms)} hint="Slow-request threshold" icon={TriangleAlert} />
          </div>

          {totals.requests === 0 ? (
            <Card className="mt-4">
              <EmptyState
                icon={Activity}
                title="No LLM requests in this window"
                message="Configure a provider in Settings and run a forecast. Usage will appear after each insight rewrite request."
              />
            </Card>
          ) : (
            <>
              <Card className="mt-4 overflow-hidden">
                <SectionTitle title="Usage trend" subtitle="Tokens and provider requests by day" />
                <div className="px-3 pb-3 pt-2">
                  {option ? <EChart option={option} ariaLabel="LLM tokens and requests over time" className="h-[260px]" /> : null}
                </div>
              </Card>

              <div className="mt-3 grid gap-3 xl:grid-cols-[0.9fr_1.1fr]">
                <Card className="overflow-hidden">
                  <SectionTitle title="Provider and model" subtitle="Volume, reliability, latency, and priced cost" />
                  <div className="scroll-thin relative overflow-x-auto">
                    <table className="w-full min-w-[560px] border-collapse">
                      <thead><tr className="border-b border-border bg-surface-muted">
                        <th className="table-header px-3 py-2 text-left">Model</th>
                        <th className="table-header px-3 py-2 text-right">Requests</th>
                        <th className="table-header px-3 py-2 text-right">Tokens</th>
                        <th className="table-header px-3 py-2 text-right">Avg latency</th>
                        <th className="table-header px-3 py-2 text-right">Cost</th>
                      </tr></thead>
                      <tbody>
                        {data.by_model.map((row) => (
                          <tr key={`${row.provider}:${row.model}`} className="border-b border-border last:border-0">
                            <td className="px-3 py-2.5"><span className="block text-meta font-medium text-text-primary">{row.model}</span><span className="text-caption text-text-muted">{row.provider}</span></td>
                            <td className="px-3 py-2.5 text-right text-meta text-text-secondary num">{row.successful_requests}/{row.requests}</td>
                            <td className="px-3 py-2.5 text-right text-meta text-text-secondary num">{compact(row.total_tokens)}</td>
                            <td className="px-3 py-2.5 text-right text-meta text-text-secondary num">{latency(row.average_latency_ms)}</td>
                            <td className="px-3 py-2.5 text-right text-meta font-medium text-text-primary num">{cost(row.cost_usd, row.priced_requests, row.requests)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>

                <Card className="overflow-hidden">
                  <SectionTitle title="Recent requests" subtitle="No prompts or credentials are stored" />
                  <div className="scroll-thin max-h-[360px] overflow-auto">
                    <table className="w-full min-w-[620px] border-collapse">
                      <thead className="sticky top-0 bg-surface-muted"><tr className="border-b border-border">
                        <th className="table-header px-3 py-2 text-left">Time</th>
                        <th className="table-header px-3 py-2 text-left">Model</th>
                        <th className="table-header px-3 py-2 text-left">Outcome</th>
                        <th className="table-header px-3 py-2 text-right">Tokens</th>
                        <th className="table-header px-3 py-2 text-right">Latency</th>
                        <th className="table-header px-3 py-2 text-right">Cost</th>
                      </tr></thead>
                      <tbody>
                        {data.recent.map((row) => {
                          const tone = row.status === "success" ? "positive" : row.status === "error" ? "negative" : "warning";
                          return (
                            <tr key={row.id} className="border-b border-border last:border-0">
                              <td className="whitespace-nowrap px-3 py-2.5 text-caption text-text-muted">{new Date(row.created_at).toLocaleString()}</td>
                              <td className="px-3 py-2.5"><span className="block max-w-[180px] truncate text-meta text-text-primary">{row.model}</span><span className="text-caption text-text-muted">{row.purpose.replaceAll("_", " ")}</span></td>
                              <td className="px-3 py-2.5"><Badge tone={tone}>{row.status}</Badge>{row.error_code ? <span className="ml-1 text-caption text-text-muted">{row.error_code}</span> : null}</td>
                              <td className="px-3 py-2.5 text-right text-meta text-text-secondary num">{row.total_tokens === null ? "—" : compact(row.total_tokens)}</td>
                              <td className="px-3 py-2.5 text-right text-meta text-text-secondary num">{latency(row.latency_ms)}</td>
                              <td className="px-3 py-2.5 text-right text-meta text-text-primary num">{row.cost_usd === null ? "—" : cost(row.cost_usd, 1, 1)}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </Card>
              </div>
            </>
          )}
        </>
      ) : null}
    </main>
  );
}
