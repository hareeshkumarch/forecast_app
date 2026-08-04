"use client";


import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  Loader2,
  Minus,
  Sigma,
  TrendingUp,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { DataQualityPanel } from "@/components/dashboard/data-quality-panel";
import { Modal } from "@/components/ui/modal";
import { Button, Field, InlineError, Input } from "@/components/ui/primitives";
import { Select, type SelectOption } from "@/components/ui/select";
import {
  useDataset,
  useDatasetQuality,
  useDatasets,
  useRefreshDashboard,
  useStartForecast,
} from "@/hooks/use-dashboard";
import { STAGE_LABELS, useForecastProgress } from "@/hooks/use-forecast-progress";
import { errorMessage } from "@/lib/errors";
import { humanizeModel } from "@/lib/format";
import { llmRunFields, loadLlmConfig } from "@/lib/llm-config";
import { cn } from "@/lib/utils";
import { toast } from "@/stores/toast-store";
import { useUiStore } from "@/stores/ui-store";
import type {
  ForecastFrequency,
  GapFill,
  MeasureAggregation,
  OutlierTreatment,
} from "@/types/api";

const NONE = "__none__";

const FREQUENCIES: SelectOption<ForecastFrequency>[] = [
  { value: "daily", label: "Daily", hint: "One point per day" },
  { value: "weekly", label: "Weekly", hint: "One point per week" },
  { value: "monthly", label: "Monthly", hint: "One point per month" },
  { value: "quarterly", label: "Quarterly", hint: "One point per quarter" },
];

const AGGREGATIONS: SelectOption<MeasureAggregation>[] = [
  { value: "sum", label: "Sum", hint: "Totals, units sold, revenue", icon: Sigma },
  { value: "mean", label: "Average", hint: "Rates, prices, utilisation", icon: TrendingUp },
  { value: "median", label: "Median", hint: "Averages with outliers", icon: TrendingUp },
  { value: "last", label: "Last value", hint: "Balances, stock on hand", icon: CalendarDays },
  { value: "min", label: "Minimum", hint: "Floors within the period", icon: Minus },
  { value: "max", label: "Maximum", hint: "Peaks within the period", icon: Minus },
];

const GAP_FILLS: SelectOption<GapFill>[] = [
  { value: "auto", label: "Automatic", hint: "Chosen from the shape of the data" },
  { value: "interpolate", label: "Interpolate", hint: "Draw a line across the hole" },
  { value: "zero", label: "Treat as zero", hint: "Nothing happened that period" },
  { value: "none", label: "Leave gaps", hint: "Forecast the calendar as it arrives" },
];

const OUTLIER_TREATMENTS: SelectOption<OutlierTreatment>[] = [
  { value: "none", label: "Keep as-is", hint: "Spikes stay in the history" },
  { value: "winsorise", label: "Damp extremes", hint: "Pull one-off spikes toward the range" },
];

type MetricFocus = "balanced" | "wmape" | "smape" | "rmse";

const METRIC_FOCUS: SelectOption<MetricFocus>[] = [
  { value: "balanced", label: "Balanced", hint: "wMAPE 50 · sMAPE 30 · RMSE 20" },
  { value: "wmape", label: "Weighted MAPE", hint: "Favours accuracy on high-volume periods" },
  { value: "smape", label: "Symmetric MAPE", hint: "Treats over- and under-forecasting alike" },
  { value: "rmse", label: "RMSE", hint: "Punishes large misses hardest" },
];

const METRIC_WEIGHTS: Record<Exclude<MetricFocus, "balanced">, Record<string, number>> = {
  wmape: { wmape: 0.7, smape: 0.2, rmse: 0.1 },
  smape: { wmape: 0.2, smape: 0.7, rmse: 0.1 },
  rmse: { wmape: 0.2, smape: 0.1, rmse: 0.7 },
};

export function ForecastModal() {
  const modal = useUiStore((state) => state.modal);
  const closeModal = useUiStore((state) => state.closeModal);
  const openModal = useUiStore((state) => state.openModal);
  const activeRunId = useUiStore((state) => state.activeRunId);
  const setActiveRun = useUiStore((state) => state.setActiveRun);
  const setRunId = useUiStore((state) => state.setRunId);
  const open = modal === "configure-forecast";

  const { data: datasets } = useDatasets();
  const startMutation = useStartForecast();
  const refreshDashboard = useRefreshDashboard();

  const [datasetId, setDatasetId] = useState("");
  const [name, setName] = useState("");
  const [frequency, setFrequency] = useState<ForecastFrequency>("monthly");
  const [horizon, setHorizon] = useState(6);
  const [confidence, setConfidence] = useState(80);
  const [regionColumn, setRegionColumn] = useState(NONE);
  const [categoryColumn, setCategoryColumn] = useState(NONE);
  const [weightColumn, setWeightColumn] = useState(NONE);
  const [aggregation, setAggregation] = useState<MeasureAggregation>("sum");
  const [gapFill, setGapFill] = useState<GapFill>("auto");
  const [outlierTreatment, setOutlierTreatment] = useState<OutlierTreatment>("none");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [maxFolds, setMaxFolds] = useState(5);
  const [metricFocus, setMetricFocus] = useState<MetricFocus>("balanced");
  const [gbmDepth, setGbmDepth] = useState(3);
  const [error, setError] = useState<string | null>(null);

  const { data: dataset } = useDataset(datasetId || null);

  const quality = useDatasetQuality(datasetId || null, {
    time_column: dataset?.time_column ?? null,
    target_column: dataset?.target_column ?? null,
    frequency,
    aggregation,
    gap_fill: gapFill,
  });

  const progress = useForecastProgress(activeRunId, (event) => {
    if (event.status === "completed") {
      setRunId(event.run_id);
      refreshDashboard();
      toast.success(
        "Forecast complete",
        event.selected_model
          ? `${humanizeModel(event.selected_model)} won the backtest; the dashboard now reflects this run.`
          : "The dashboard now reflects this run.",
      );
    } else if (event.status === "failed") {
      toast.error("Forecast failed", event.error ?? "The run did not finish.");
    }
  });

  useEffect(() => {
    if (open && datasets && datasets.length > 0 && !datasetId) {
      const first = datasets[0];
      if (first) setDatasetId(first.id);
    }
  }, [open, datasets, datasetId]);

  useEffect(() => {
    if (!dataset) return;
    setName(`${dataset.name} forecast`);
    setFrequency(dataset.frequency ?? "monthly");
    setHorizon(dataset.horizon ?? 6);

    const dimensions = dataset.columns.filter((column) => column.role === "dimension");
    const region = dimensions.find((column) =>
      /region|country|market|territory|geo/i.test(column.name),
    );
    const category = dimensions.find(
      (column) => column !== region && /categ|product|segment|sku|brand/i.test(column.name),
    );
    const weight = dataset.columns.find((column) => column.role === "weight");

    setRegionColumn(region?.name ?? dimensions[0]?.name ?? NONE);
    setCategoryColumn(category?.name ?? dimensions[1]?.name ?? NONE);
    setWeightColumn(weight?.name ?? NONE);
    setAggregation(suggestAggregation(dataset.target_column));
  }, [dataset]);

  useEffect(() => {
    if (!open) {
      setError(null);
      startMutation.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function handleRun() {
    if (!datasetId) {
      setError("Choose a dataset to forecast.");
      return;
    }
    if (quality.data?.blocked) {
      setError(
        quality.data.issues.find((issue) => issue.severity === "severe")?.remedy ??
          "Fix the data problems listed above before running a forecast.",
      );
      return;
    }
    setError(null);

    const metricWeights = metricFocus === "balanced" ? undefined : METRIC_WEIGHTS[metricFocus];

    startMutation.mutate(
      {
        dataset_id: datasetId,
        name: name.trim() || undefined,
        frequency,
        horizon,
        confidence_level: confidence / 100,
        region_column: regionColumn === NONE ? null : regionColumn,
        category_column: categoryColumn === NONE ? null : categoryColumn,
        weight_column: weightColumn === NONE ? null : weightColumn,
        aggregation,
        gap_fill: gapFill,
        outlier_treatment: outlierTreatment,
        max_folds: maxFolds,
        metric_weights: metricWeights,
        gbm_max_depth: gbmDepth,

        ...llmRunFields(loadLlmConfig()),
      },
      {
        onSuccess: (run) => setActiveRun(run.id),
        onError: (mutationError) => setError(errorMessage(mutationError)),
      },
    );
  }

  function handleClose() {
    
    if (progress.status === "completed" || progress.status === "failed") {
      setActiveRun(null);
    }
    closeModal();
  }

  const dimensions = dataset?.columns.filter((column) => column.role === "dimension") ?? [];
  const numerics = dataset?.columns.filter((column) => column.kind === "numeric") ?? [];
  const blocked = quality.data?.blocked ?? false;

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Run Forecast"
      description="Fits every eligible candidate model, backtests them, and selects a winner."
      size="md"
      footer={
        activeRunId ? (
          <Button variant="secondary" onClick={handleClose}>
            {progress.status === "completed" || progress.status === "failed" ? "Close" : "Run in background"}
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={handleClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={handleRun}
              loading={startMutation.isPending}
              disabled={blocked}
              title={blocked ? "Resolve the data problems listed in the panel first" : undefined}
            >
              Run Forecast
            </Button>
          </>
        )
      }
    >
      {activeRunId ? (
        <ProgressPanel progress={progress} />
      ) : (
        <div className="space-y-4">
          <Field label="Dataset" required>
            <Select
              value={datasetId}
              onChange={setDatasetId}
              placeholder="Select a dataset…"
              options={(datasets ?? []).map((item) => ({
                value: item.id,
                label: item.name,
                hint: `${item.row_count.toLocaleString()} rows · ${item.column_count} columns`,
              }))}
            />
          </Field>

          <Field label="Run name">
            <Input value={name} onChange={(event) => setName(event.target.value)} />
          </Field>

          <Section title="What to forecast">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Field label="Frequency" hint="Period the series is on" required>
                <Select value={frequency} onChange={setFrequency} options={FREQUENCIES} />
              </Field>

              <Field label="Horizon" hint="Periods ahead" required>
                <Input
                  type="number"
                  min={1}
                  max={365}
                  value={horizon}
                  onChange={(event) => setHorizon(Number(event.target.value) || 1)}
                />
              </Field>

              <Field label="Confidence %" hint="Width of the band">
                <Input
                  type="number"
                  min={51}
                  max={99}
                  value={confidence}
                  onChange={(event) => setConfidence(Number(event.target.value) || 80)}
                />
              </Field>
            </div>
          </Section>

          <Section title="Break it down by" note="Optional">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Field label="Region" hint="Splits the total by geography">
                <DimensionSelect
                  value={regionColumn}
                  onChange={setRegionColumn}
                  options={dimensions.map((column) => column.name)}
                />
              </Field>
              <Field label="Category" hint="Splits the total by product">
                <DimensionSelect
                  value={categoryColumn}
                  onChange={setCategoryColumn}
                  options={dimensions.map((column) => column.name)}
                />
              </Field>
              <Field label="Weight" hint="Used for weighted MAPE">
                <DimensionSelect
                  value={weightColumn}
                  onChange={setWeightColumn}
                  options={numerics.map((column) => column.name)}
                />
              </Field>
            </div>
          </Section>

          <Section title="How to read the data">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Field label="Combine rows by" hint="Collapses duplicate periods">
                <Select value={aggregation} onChange={setAggregation} options={AGGREGATIONS} />
              </Field>

              <Field label="Missing periods" hint="Keeps the calendar regular">
                <Select value={gapFill} onChange={setGapFill} options={GAP_FILLS} />
              </Field>

              <Field label="Outliers" hint="Handles one-off spikes">
                <Select
                  value={outlierTreatment}
                  onChange={setOutlierTreatment}
                  options={OUTLIER_TREATMENTS}
                />
              </Field>
            </div>

            {datasetId ? (
              dataset && !dataset.time_column ? (
                <p className="mt-3 rounded-card border border-border bg-surface-muted px-3 py-2 text-caption text-text-secondary">
                  Pick a time column and a target for this dataset to see a quality check before you
                  run.
                </p>
              ) : (
                <div className="mt-3">
                  <DataQualityPanel
                    report={quality.data}
                    isLoading={quality.isLoading}
                    error={quality.error}
                  />
                </div>
              )
            ) : null}
          </Section>

          <div className="border-t border-border pt-3">
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              aria-expanded={showAdvanced}
              aria-controls="advanced-model-settings"
              className="flex items-center gap-1.5 rounded-input text-caption font-medium text-text-secondary transition-colors duration-fast hover:text-text-primary"
            >
              <ChevronRight
                className={cn(
                  "h-3.5 w-3.5 transition-transform duration-fast",
                  showAdvanced && "rotate-90",
                )}
                aria-hidden
              />
              Advanced model settings
            </button>

            {showAdvanced ? (
              <div
                id="advanced-model-settings"
                className="mt-3 grid grid-cols-1 gap-3 rounded-card border border-border bg-surface-muted/40 p-3 sm:grid-cols-3"
              >
                <Field label="Validation folds" hint="Backtest windows, 1 to 10">
                  <Input
                    type="number"
                    min={1}
                    max={10}
                    value={maxFolds}
                    onChange={(e) => setMaxFolds(Number(e.target.value) || 5)}
                  />
                </Field>

                <Field label="Metric emphasis" hint="How candidates are scored">
                  <Select value={metricFocus} onChange={setMetricFocus} options={METRIC_FOCUS} />
                </Field>

                <Field label="Tree depth" hint="Gradient boosting only">
                  <Input
                    type="number"
                    min={1}
                    max={10}
                    value={gbmDepth}
                    onChange={(e) => setGbmDepth(Number(e.target.value) || 3)}
                  />
                </Field>
              </div>
            ) : null}
          </div>

          <p className="text-caption text-text-muted">
            Insights are reworded by an LLM when one is configured in{" "}
            <button
              type="button"
              onClick={() => openModal("settings")}
              className="font-medium text-accent hover:underline"
            >
              Settings
            </button>
            . The numbers are computed either way.
          </p>

          <InlineError message={error ?? undefined} />
        </div>
      )}
    </Modal>
  );
}

function Section({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <section className="border-t border-border pt-3">
      <div className="mb-2.5 flex items-baseline gap-2">
        <h3 className="eyebrow">{title}</h3>
        {note ? <span className="text-caption text-text-muted">{note}</span> : null}
      </div>
      {children}
    </section>
  );
}

function suggestAggregation(target: string | null): MeasureAggregation {
  if (!target) return "sum";
  if (/rate|ratio|pct|percent|price|avg|average|score|index|margin|temp/i.test(target)) {
    return "mean";
  }
  if (/balance|stock|inventory|level|headcount|on_hand/i.test(target)) return "last";
  return "sum";
}

function DimensionSelect({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (next: string) => void;
  options: string[];
}) {
  return (
    <Select
      value={value}
      onChange={onChange}
      options={[
        { value: NONE, label: "None" },
        ...options.map((name) => ({ value: name, label: name })),
      ]}
    />
  );
}

function ProgressPanel({
  progress,
}: {
  progress: ReturnType<typeof useForecastProgress>;
}) {
  const percent = Math.round(progress.progress * 100);
  const failed = progress.status === "failed";
  const done = progress.status === "completed";

  const stages = [
    "aggregating",
    "backtesting",
    "fitting",
    "persisting",
    "generating_insights",
    "complete",
  ];
  const currentIndex = stages.indexOf(progress.stage);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2.5">
        {done ? (
          <CheckCircle2 className="h-5 w-5 text-positive" aria-hidden />
        ) : failed ? (
          <AlertTriangle className="h-5 w-5 text-negative" aria-hidden />
        ) : (
          <Loader2 className="h-5 w-5 animate-spin text-accent" aria-hidden />
        )}
        <div className="min-w-0">
          <p className="text-body font-medium text-text-primary">
            {STAGE_LABELS[progress.stage] ?? progress.stage}
          </p>
          {progress.message ? (
            <p className="text-caption text-text-muted">{progress.message}</p>
          ) : null}
        </div>
        <span className="ml-auto text-meta font-semibold text-text-secondary num">{percent}%</span>
      </div>

      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-surface-muted"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-300",
            failed ? "bg-negative" : done ? "bg-positive" : "bg-accent",
          )}
          style={{ width: `${Math.max(percent, 3)}%` }}
        />
      </div>

      <ol className="space-y-1.5">
        {stages.slice(0, -1).map((stage, index) => {
          const isDone = done || (currentIndex >= 0 && index < currentIndex);
          const isCurrent = !done && index === currentIndex;
          return (
            <li key={stage} className="flex items-center gap-2">
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  isDone ? "bg-positive" : isCurrent ? "bg-accent" : "bg-border-strong",
                )}
                aria-hidden
              />
              <span
                className={cn(
                  "text-caption",
                  isDone || isCurrent ? "text-text-primary" : "text-text-muted",
                )}
              >
                {STAGE_LABELS[stage]}
              </span>
            </li>
          );
        })}
      </ol>

      {progress.error ? (
        <div className="flex items-start gap-2 rounded-card border border-negative-border bg-negative-soft px-3 py-2">
          <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0 text-negative" aria-hidden />
          <p className="text-caption text-negative">{progress.error}</p>
        </div>
      ) : null}

      {done ? (
        <p className="rounded-card border border-positive-border bg-positive-soft px-3 py-2 text-caption text-positive">
          Forecast complete. The dashboard now reflects this run.
        </p>
      ) : null}
    </div>
  );
}
