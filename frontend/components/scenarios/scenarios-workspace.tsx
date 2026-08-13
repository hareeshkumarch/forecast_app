"use client";

import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  FlaskConical,
  GitCompareArrows,
  Plus,
  RefreshCw,
  Save,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { EChart, type ChartOption } from "@/components/charts/echart";
import { RefreshButton } from "@/components/ui/refresh-button";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Skeleton,
} from "@/components/ui/primitives";
import { Select } from "@/components/ui/select";
import {
  useDeleteSavedScenario,
  useForecastMonitoring,
  useForecastRuns,
  useRetryForecastRun,
  useRunComparison,
  useSaveScenario,
  useSavedScenarios,
  useScenarioDrivers,
  useSimulateScenario,
} from "@/hooks/use-dashboard";
import { axisLabel, axisLine, axisValueFormatter, chartColors, splitLine, tooltipStyle } from "@/lib/chart-theme";
import {
  formatCompact,
  formatMetric,
  formatPercent,
  formatRelativeTime,
  formatSignedPercent,
  humanizeKey,
  humanizeModel,
} from "@/lib/format";
import { cn } from "@/lib/utils";
import { confirm } from "@/stores/confirm-store";
import { usePrefsStore } from "@/stores/prefs-store";
import { useUiStore } from "@/stores/ui-store";
import type { ForecastMonitorItem, ScenarioSimulation } from "@/types/api";

type WorkspaceTab = "planner" | "compare" | "monitor";

const TABS: { id: WorkspaceTab; label: string; icon: typeof FlaskConical }[] = [
  { id: "planner", label: "Scenario planner", icon: FlaskConical },
  { id: "compare", label: "Compare runs", icon: GitCompareArrows },
  { id: "monitor", label: "Monitoring", icon: Activity },
];

function SliderField({
  label,
  hint,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  hint: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <p className="text-meta font-medium text-text-primary">{label}</p>
          <p className="text-caption text-text-muted">{hint}</p>
        </div>
        <span className="rounded-chip bg-surface-muted px-2 py-1 text-meta font-semibold text-text-primary num">
          {value}%
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={1}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="mt-3 h-2 w-full cursor-pointer accent-accent"
        aria-label={label}
      />
      <div className="mt-1 flex justify-between text-caption text-text-muted num">
        <span>{min}%</span>
        <span>{max}%</span>
      </div>
    </div>
  );
}

function ScenarioChart({ result }: { result: ScenarioSimulation }) {
  const resolvedTheme = usePrefsStore((state) => state.resolvedTheme);
  const option = useMemo<ChartOption>(() => {
    // Re-read CSS variables whenever the resolved theme changes.
    void resolvedTheme;
    const colors = chartColors();
    return {
      animationDuration: 420,
      animationEasing: "cubicOut",
      color: [colors.textMuted, colors.accent],
      grid: { left: 12, right: 12, top: 34, bottom: 22, containLabel: true },
      legend: {
        top: 0,
        right: 0,
        textStyle: { color: colors.textSecondary, fontSize: 10 },
      },
      tooltip: {
        trigger: "axis",
        ...tooltipStyle(colors),
        valueFormatter: (value: unknown) => formatCompact(Number(value)),
      },
      xAxis: {
        type: "category",
        data: result.points.map((point) => point.period),
        axisLabel: { ...axisLabel(colors), hideOverlap: true },
        axisLine: axisLine(colors),
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        axisLabel: { ...axisLabel(colors), formatter: axisValueFormatter() },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: splitLine(colors),
      },
      series: [
        {
          name: "Baseline",
          type: "line",
          data: result.points.map((point) => point.baseline_forecast),
          symbol: "none",
          lineStyle: { width: 1.5, type: "dashed", color: colors.textMuted },
        },
        {
          name: "Scenario",
          type: "line",
          data: result.points.map((point) => point.simulated_forecast),
          symbol: "none",
          smooth: 0.18,
          lineStyle: { width: 2.5, color: colors.accent },
          areaStyle: { color: colors.accentSoft, opacity: 0.45 },
        },
      ],
    };
  }, [resolvedTheme, result]);

  return <EChart option={option} ariaLabel="Baseline and simulated forecast by period" className="h-64 sm:h-72" />;
}

function ScenarioPlanner() {
  const openModal = useUiStore((state) => state.openModal);
  const runs = useForecastRuns({ state: "completed", sort: "newest", limit: 50 });
  const [runId, setRunId] = useState<string | null>(null);
  const [name, setName] = useState("Planning scenario");
  const [description, setDescription] = useState("");
  const [volumePct, setVolumePct] = useState(100);
  const [targetShift, setTargetShift] = useState(0);
  const [driverPcts, setDriverPcts] = useState<Record<string, number>>({});
  const [selectedSavedId, setSelectedSavedId] = useState<string | null>(null);
  const simulation = useSimulateScenario();
  const save = useSaveScenario();
  const remove = useDeleteSavedScenario();
  const scenarios = useSavedScenarios(runId);
  const drivers = useScenarioDrivers(runId);

  const completedRuns = useMemo(() => runs.data?.rows ?? [], [runs.data?.rows]);
  useEffect(() => {
    if (!runId && completedRuns[0]) setRunId(completedRuns[0].id);
    if (runId && completedRuns.length > 0 && !completedRuns.some((run) => run.id === runId)) {
      setRunId(completedRuns[0]!.id);
    }
  }, [completedRuns, runId]);

  useEffect(() => {
    simulation.reset();
    setSelectedSavedId(null);
    setDriverPcts({});
  }, [runId]); // eslint-disable-line react-hooks/exhaustive-deps

  const selectedSaved = scenarios.data?.find((scenario) => scenario.id === selectedSavedId) ?? null;
  const result = selectedSaved?.result ?? simulation.data ?? null;
  const driverMultipliers = Object.fromEntries(
    Object.entries(driverPcts)
      .filter(([, value]) => value !== 100)
      .map(([driver, value]) => [driver, value / 100]),
  );

  const payload = runId ? {
    runId,
    volume_multiplier: volumePct / 100,
    target_shift_pct: targetShift,
    driver_multipliers: driverMultipliers,
  } : null;

  function preview() {
    if (!payload) return;
    setSelectedSavedId(null);
    simulation.mutate(payload);
  }

  function editAssumptions() {
    setSelectedSavedId(null);
    simulation.reset();
  }

  function saveCurrent() {
    if (!payload || !name.trim()) return;
    save.mutate(
      { ...payload, name: name.trim(), description: description.trim() || null },
      { onSuccess: (scenario) => { simulation.reset(); setSelectedSavedId(scenario.id); } },
    );
  }

  async function deleteScenario(id: string, scenarioName: string) {
    if (!runId) return;
    const accepted = await confirm({
      title: "Delete this scenario?",
      message: `“${scenarioName}” will be removed. The source forecast stays untouched.`,
      confirmLabel: "Delete scenario",
    });
    if (!accepted) return;
    remove.mutate({ runId, scenarioId: id });
    if (selectedSavedId === id) setSelectedSavedId(null);
  }

  if (runs.isLoading) {
    return <div className="grid gap-3 lg:grid-cols-[minmax(300px,0.8fr)_minmax(0,1.4fr)]"><Skeleton className="h-[34rem]" /><Skeleton className="h-[34rem]" /></div>;
  }
  if (runs.isError) return <Card><ErrorState error={runs.error} onRetry={() => void runs.refetch()} /></Card>;
  if (completedRuns.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={FlaskConical}
          title="A completed forecast unlocks scenarios"
          message="Create a forecast first, then adjust its assumptions without changing the issued result."
          action={<Button variant="primary" icon={Plus} onClick={() => openModal("configure-forecast")}>New forecast</Button>}
        />
      </Card>
    );
  }

  const runOptions = completedRuns.map((run) => ({
    value: run.id,
    label: run.name,
    hint: `${humanizeModel(run.selected_model)} · ${run.horizon} ${humanizeKey(run.frequency).toLowerCase()} periods`,
  }));

  return (
    <div className="grid min-w-0 gap-3 xl:grid-cols-[minmax(320px,0.78fr)_minmax(0,1.35fr)]">
      <div className="space-y-3">
        <Card className="p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="panel-title">Assumptions</h2>
              <p className="mt-0.5 text-caption text-text-muted">Re-price an issued forecast. The model itself is never rewritten.</p>
            </div>
            <Badge tone="accent">Non-destructive</Badge>
          </div>

          <div className="mt-4 space-y-5">
            <Field label="Source forecast" required>
              <Select value={runId ?? completedRuns[0]!.id} onChange={setRunId} options={runOptions} label="Source forecast" />
            </Field>
            <SliderField label="Demand / volume" hint="Scale the forecasted quantity" value={volumePct} min={50} max={150} onChange={(value) => { setVolumePct(value); editAssumptions(); }} />
            <SliderField label="Target shift" hint="Apply a price, rate, or value change" value={targetShift} min={-50} max={100} onChange={(value) => { setTargetShift(value); editAssumptions(); }} />

            {drivers.data && drivers.data.rows.length > 0 ? (
              <div className="border-t border-border pt-4">
                <p className="text-meta font-medium text-text-primary">Driver assumptions</p>
                <p className="text-caption text-text-muted">Only measured drivers from this run are available.</p>
                <div className="mt-3 space-y-3">
                  {drivers.data.rows.slice(0, 6).map((driver) => (
                    <div key={driver.driver} className="flex items-center gap-3">
                      <span className="min-w-0 flex-1 truncate text-caption text-text-secondary">{humanizeKey(driver.driver)}</span>
                      <input
                        type="range"
                        min={50}
                        max={150}
                        value={driverPcts[driver.driver] ?? 100}
                        onChange={(event) => {
                          const value = Number(event.target.value);
                          setDriverPcts((current) => ({ ...current, [driver.driver]: value }));
                          editAssumptions();
                        }}
                        className="h-2 w-28 accent-accent sm:w-36"
                        aria-label={`${driver.driver} multiplier`}
                      />
                      <span className="w-11 text-right text-caption font-medium text-text-primary num">{driverPcts[driver.driver] ?? 100}%</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>

          <div className="mt-5 flex flex-wrap gap-2 border-t border-border pt-4">
            <Button variant="primary" icon={FlaskConical} loading={simulation.isPending} onClick={preview}>Preview impact</Button>
            <Button icon={RefreshCw} onClick={() => { setVolumePct(100); setTargetShift(0); setDriverPcts({}); editAssumptions(); }}>Reset</Button>
          </div>
        </Card>

        <Card className="p-4">
          <h2 className="panel-title">Save this view</h2>
          <div className="mt-3 space-y-3">
            <Field label="Scenario name" required>
              <Input value={name} maxLength={160} onChange={(event) => setName(event.target.value)} />
            </Field>
            <Field label="Planning note" hint="Optional context for your team or future self.">
              <textarea
                value={description}
                maxLength={1000}
                onChange={(event) => setDescription(event.target.value)}
                className="min-h-20 w-full resize-y rounded-input border border-border bg-surface px-2.5 py-2 text-meta text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
              />
            </Field>
            <Button variant="primary" icon={Save} loading={save.isPending} disabled={!name.trim() || !runId} onClick={saveCurrent}>Save and calculate</Button>
          </div>
        </Card>
      </div>

      <div className="min-w-0 space-y-3">
        <Card className="min-w-0 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="panel-title">Scenario impact</h2>
              <p className="mt-0.5 text-caption text-text-muted">Baseline against the currently selected assumptions.</p>
            </div>
            {result ? <Badge tone={result.total_delta >= 0 ? "positive" : "negative"}>{formatSignedPercent(result.total_delta_pct)}</Badge> : null}
          </div>
          {simulation.isPending ? (
            <div className="mt-4 space-y-3"><Skeleton className="h-20" /><Skeleton className="h-72" /></div>
          ) : simulation.isError ? (
            <ErrorState error={simulation.error} onRetry={preview} />
          ) : result ? (
            <div className="mt-4">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {[
                  ["Baseline", formatCompact(result.baseline_total)],
                  ["Scenario", formatCompact(result.simulated_total)],
                  ["Downside", formatCompact(result.simulated_worst_case_total)],
                  ["Upside", formatCompact(result.simulated_best_case_total)],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-card border border-border bg-surface-muted/60 p-3">
                    <p className="text-caption text-text-muted">{label}</p>
                    <p className="mt-1 truncate text-subhead font-semibold text-text-primary num">{value}</p>
                  </div>
                ))}
              </div>
              <div className="mt-4"><ScenarioChart result={result} /></div>
              <p className="mt-3 text-caption text-text-muted">This is a sensitivity view based on measured driver leverage; it is not a refitted model. Uncertainty widens as assumptions move further from baseline.</p>
            </div>
          ) : (
            <EmptyState icon={FlaskConical} title="Ready for an assumption" message="Adjust demand, target, or driver values and preview the effect across the forecast horizon." />
          )}
        </Card>

        <Card className="p-4">
          <div className="flex items-baseline justify-between gap-3">
            <div>
              <h2 className="panel-title">Saved scenarios</h2>
              <p className="mt-0.5 text-caption text-text-muted">Stored with their calculated result for reproducible planning.</p>
            </div>
            <span className="text-caption text-text-muted num">{scenarios.data?.length ?? 0}</span>
          </div>
          {scenarios.isLoading ? (
            <div className="mt-3 space-y-2"><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
          ) : scenarios.isError ? (
            <ErrorState error={scenarios.error} onRetry={() => void scenarios.refetch()} />
          ) : scenarios.data && scenarios.data.length > 0 ? (
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {scenarios.data.map((scenario) => (
                <div
                  key={scenario.id}
                  className={cn(
                    "group relative rounded-card border text-left transition-colors duration-fast",
                    selectedSavedId === scenario.id ? "border-accent bg-accent-soft/50" : "border-border bg-surface hover:border-border-strong",
                  )}
                >
                  <button type="button" onClick={() => {
                    setSelectedSavedId(scenario.id);
                    setName(scenario.name);
                    setDescription(scenario.description ?? "");
                    setVolumePct(Math.round(scenario.volume_multiplier * 100));
                    setTargetShift(scenario.target_shift_pct);
                    setDriverPcts(Object.fromEntries(Object.entries(scenario.driver_multipliers).map(([driver, value]) => [driver, Math.round(value * 100)])));
                    simulation.reset();
                  }} className="block w-full p-3 pr-11 text-left">
                    <div className="min-w-0">
                      <p className="truncate text-meta font-semibold text-text-primary">{scenario.name}</p>
                      <p className="mt-0.5 text-caption text-text-muted">{formatRelativeTime(scenario.created_at)} · {formatSignedPercent(scenario.result.total_delta_pct)}</p>
                    </div>
                    {scenario.description ? <p className="mt-2 line-clamp-2 text-caption text-text-secondary">{scenario.description}</p> : null}
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete ${scenario.name}`}
                    onClick={() => void deleteScenario(scenario.id, scenario.name)}
                    className="absolute right-2 top-2 flex h-7 w-7 items-center justify-center rounded-input text-text-muted hover:bg-negative-soft hover:text-negative"
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="No saved scenarios" message="Save a sensitivity view to make it available here." className="py-6" />
          )}
        </Card>
      </div>
    </div>
  );
}

function RunComparisonPanel() {
  const runs = useForecastRuns({ state: "completed", sort: "newest", limit: 50 });
  const rows = useMemo(() => runs.data?.rows ?? [], [runs.data?.rows]);
  const [leftId, setLeftId] = useState<string | null>(null);
  const [rightId, setRightId] = useState<string | null>(null);

  useEffect(() => {
    if (!leftId && rows[1]) setLeftId(rows[1].id);
    if (!rightId && rows[0]) setRightId(rows[0].id);
  }, [leftId, rightId, rows]);

  const comparison = useRunComparison(leftId, rightId);
  if (runs.isLoading) return <Skeleton className="h-[34rem]" />;
  if (runs.isError) return <Card><ErrorState error={runs.error} onRetry={() => void runs.refetch()} /></Card>;
  if (rows.length < 2) return <Card><EmptyState icon={GitCompareArrows} title="Two completed runs are needed" message="Create another forecast to compare method, total, accuracy, and backtest metrics." /></Card>;

  const options = rows.map((run) => ({ value: run.id, label: run.name, hint: `${humanizeModel(run.selected_model)} · ${formatRelativeTime(run.created_at)}` }));
  const data = comparison.data;
  return (
    <div className="space-y-3">
      <Card className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><h2 className="panel-title">Run comparison</h2><p className="mt-0.5 text-caption text-text-muted">The left run is the baseline; deltas show how the right run changed.</p></div>
          <Badge tone="accent">Issued results</Badge>
        </div>
        <div className="mt-4 grid items-end gap-3 md:grid-cols-[1fr_auto_1fr]">
          <Field label="Baseline run"><Select value={leftId ?? rows[1]!.id} onChange={setLeftId} options={options.map((option) => ({ ...option, disabled: option.value === rightId }))} /></Field>
          <GitCompareArrows className="mb-2 hidden h-4 w-4 text-text-muted md:block" aria-hidden />
          <Field label="Comparison run"><Select value={rightId ?? rows[0]!.id} onChange={setRightId} options={options.map((option) => ({ ...option, disabled: option.value === leftId }))} /></Field>
        </div>
      </Card>

      {comparison.isLoading || !data ? (
        comparison.isError ? <Card><ErrorState error={comparison.error} onRetry={() => void comparison.refetch()} /></Card> : <Skeleton className="h-[28rem]" />
      ) : (
        <>
          <div className="grid gap-3 lg:grid-cols-2">
            {[data.left, data.right].map((run, index) => (
              <Card key={run.run_id} className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0"><p className="text-caption text-text-muted">{index === 0 ? "Baseline" : "Comparison"}</p><h3 className="mt-0.5 truncate text-subhead font-semibold text-text-primary">{run.name}</h3></div>
                  <Badge>{humanizeModel(run.model)}</Badge>
                </div>
                <dl className="mt-4 grid grid-cols-2 gap-3">
                  <div><dt className="text-caption text-text-muted">Forecast total</dt><dd className="mt-0.5 text-heading font-semibold text-text-primary num">{formatCompact(run.forecast_total)}</dd></div>
                  <div><dt className="text-caption text-text-muted">Realized accuracy</dt><dd className="mt-0.5 text-heading font-semibold text-text-primary num">{formatPercent(run.realized_accuracy)}</dd></div>
                  <div><dt className="text-caption text-text-muted">Horizon</dt><dd className="mt-0.5 text-meta font-medium text-text-primary num">{run.horizon} {humanizeKey(run.frequency).toLowerCase()} periods</dd></div>
                  <div><dt className="text-caption text-text-muted">Confidence</dt><dd className="mt-0.5 text-meta font-medium text-text-primary num">{formatPercent(run.confidence_level * 100, 0)}</dd></div>
                </dl>
              </Card>
            ))}
          </div>

          <Card className="overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
              <div><h2 className="panel-title">What changed</h2><p className="mt-0.5 text-caption text-text-muted">Positive means the comparison run is higher.</p></div>
              <Badge tone={data.forecast_total_delta >= 0 ? "positive" : "negative"}>Total {formatSignedPercent(data.forecast_total_delta_pct)}</Badge>
            </div>
            <div className="scroll-thin overflow-x-auto">
              <table className="w-full min-w-[620px] border-collapse">
                <thead><tr className="border-b border-border"><th className="table-header px-4 py-2 text-left">Measure</th><th className="table-header px-4 py-2 text-right">Baseline</th><th className="table-header px-4 py-2 text-right">Comparison</th><th className="table-header px-4 py-2 text-right">Change</th></tr></thead>
                <tbody>
                  <tr className="border-b border-border bg-surface-muted/40"><td className="cell px-4 font-medium text-text-primary">Forecast total</td><td className="cell px-4 text-right num">{formatCompact(data.left.forecast_total)}</td><td className="cell px-4 text-right num">{formatCompact(data.right.forecast_total)}</td><td className={cn("cell px-4 text-right font-semibold num", data.forecast_total_delta >= 0 ? "text-positive" : "text-negative")}>{formatCompact(data.forecast_total_delta)} ({formatSignedPercent(data.forecast_total_delta_pct)})</td></tr>
                  {data.metrics.map((metric) => (
                    <tr key={metric.name} className="border-b border-border last:border-0">
                      <td className="cell px-4 font-medium text-text-primary">{humanizeKey(metric.name)}</td>
                      <td className="cell px-4 text-right text-text-secondary num">{metric.left === null ? "—" : formatMetric(metric.left, metric.unit, false)}</td>
                      <td className="cell px-4 text-right text-text-secondary num">{metric.right === null ? "—" : formatMetric(metric.right, metric.unit, false)}</td>
                      <td className={cn("cell px-4 text-right font-medium num", metric.delta === null ? "text-text-muted" : metric.delta <= 0 ? "text-positive" : "text-warning")}>{metric.delta === null ? "—" : `${formatMetric(metric.delta, metric.unit, false)} (${formatSignedPercent(metric.delta_pct)})`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

const MONITOR_TONE = {
  critical: "negative",
  warning: "warning",
  info: "accent",
} as const;

function MonitorRow({ row }: { row: ForecastMonitorItem }) {
  const retry = useRetryForecastRun();
  const healthy = !row.alert;
  return (
    <div className="flex flex-col gap-3 border-b border-border px-4 py-3 last:border-0 sm:flex-row sm:items-center">
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <span className={cn("mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full", healthy ? "bg-positive-soft text-positive" : row.alert_level === "critical" ? "bg-negative-soft text-negative" : "bg-warning-soft text-warning")}>
          {healthy ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
        </span>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2"><p className="truncate text-meta font-semibold text-text-primary">{row.name}</p><Badge tone={row.alert_level ? MONITOR_TONE[row.alert_level] : "positive"}>{row.alert_level ? humanizeKey(row.alert_level) : "Healthy"}</Badge></div>
          <p className="mt-0.5 text-caption text-text-muted">{row.alert ?? `No drift detected${row.scored_periods ? ` across ${row.scored_periods} scored periods` : ""}.`}</p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-x-5 gap-y-1 sm:flex sm:items-center sm:gap-5">
        <div className="text-right"><p className="text-caption text-text-muted">Accuracy</p><p className="text-meta font-semibold text-text-primary num">{formatPercent(row.realized_accuracy)}</p></div>
        <div className="text-right"><p className="text-caption text-text-muted">Bias</p><p className="text-meta font-semibold text-text-primary num">{formatPercent(row.realized_bias)}</p></div>
        {row.can_retry ? <Button size="sm" icon={RefreshCw} loading={retry.isPending} onClick={() => retry.mutate(row.run_id)}>Retry</Button> : null}
      </div>
    </div>
  );
}

function MonitoringPanel() {
  const monitor = useForecastMonitoring();
  if (monitor.isLoading) return <Skeleton className="h-[34rem]" />;
  if (monitor.isError || !monitor.data) return <Card><ErrorState error={monitor.error} onRetry={() => void monitor.refetch()} /></Card>;
  const data = monitor.data;
  const stats = [
    { label: "Healthy", value: data.healthy, tone: "text-positive", icon: CheckCircle2 },
    { label: "Needs attention", value: data.attention, tone: "text-warning", icon: AlertTriangle },
    { label: "Failed", value: data.failed, tone: "text-negative", icon: Activity },
    { label: "In progress", value: data.active, tone: "text-accent", icon: RefreshCw },
  ];
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {stats.map((stat) => <Card key={stat.label} className="p-3.5"><div className="flex items-center justify-between"><p className="text-caption text-text-muted">{stat.label}</p><stat.icon className={cn("h-4 w-4", stat.tone)} /></div><p className="mt-2 text-kpi font-semibold text-text-primary num">{stat.value}</p></Card>)}
      </div>
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-3.5">
          <div><h2 className="panel-title">Forecast health</h2><p className="mt-0.5 text-caption text-text-muted">Failed jobs, elapsed unscored forecasts, and realized wMAPE above {formatPercent(data.drift_wmape_limit)}.</p></div>
          <RefreshButton updatedAt={monitor.dataUpdatedAt} isFetching={monitor.isFetching} onRefresh={() => void monitor.refetch()} />
        </div>
        {data.rows.length > 0 ? data.rows.map((row) => <MonitorRow key={row.run_id} row={row} />) : <EmptyState icon={ShieldCheck} title="No runs to monitor" message="Forecast health appears here as soon as a run starts." />}
      </Card>
    </div>
  );
}

export function ScenariosWorkspace() {
  const [tab, setTab] = useState<WorkspaceTab>("planner");
  return (
    <main id="main-content" className="scroll-thin min-w-0 flex-1 overflow-y-auto bg-canvas px-4 py-4 sm:px-6 sm:py-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h1 className="text-heading font-semibold tracking-[-0.015em] text-text-primary">Scenarios</h1><p className="mt-0.5 text-meta text-text-secondary">Test assumptions, compare issued runs, and catch forecast drift.</p></div>
        <Badge tone="accent" className="gap-1.5"><ShieldCheck className="h-3.5 w-3.5" aria-hidden />Source forecasts stay locked</Badge>
      </div>
      <div className="scroll-thin mt-4 overflow-x-auto" role="tablist" aria-label="Scenario tools">
        <div className="inline-flex min-w-max gap-1 rounded-card border border-border bg-surface p-1">
          {TABS.map((item) => {
            const Icon = item.icon;
            return <button key={item.id} type="button" role="tab" aria-selected={tab === item.id} onClick={() => setTab(item.id)} className={cn("flex h-9 items-center gap-2 rounded-input px-3 text-meta font-medium transition-colors duration-fast", tab === item.id ? "bg-accent text-on-accent" : "text-text-secondary hover:bg-surface-muted hover:text-text-primary")}><Icon className="h-3.5 w-3.5" aria-hidden />{item.label}</button>;
          })}
        </div>
      </div>
      <section className="mt-3" role="tabpanel">
        {tab === "planner" ? <ScenarioPlanner /> : tab === "compare" ? <RunComparisonPanel /> : <MonitoringPanel />}
      </section>
    </main>
  );
}
