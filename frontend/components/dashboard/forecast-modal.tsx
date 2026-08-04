"use client";


import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { Button, Field, Input } from "@/components/ui/primitives";
import {
  useDataset,
  useDatasets,
  useRefreshDashboard,
  useStartForecast,
} from "@/hooks/use-dashboard";
import { STAGE_LABELS, useForecastProgress } from "@/hooks/use-forecast-progress";
import { humanizeModel } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import type { ForecastFrequency } from "@/types/api";

const FREQUENCIES: ForecastFrequency[] = ["daily", "weekly", "monthly", "quarterly"];
const NONE = "__none__";

const PROVIDER_MODELS: Record<string, string[]> = {
  openai: ["gpt-4o-mini", "gpt-4o", "o3-mini"],
  anthropic: ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"],
  groq: ["llama-3.3-70b-versatile", "deepseek-r1-distill-llama-70b"],
  xai: ["grok-2-latest", "grok-beta"],
  gemini: ["gemini-2.5-flash", "gemini-2.5-pro"],
  openrouter: ["anthropic/claude-3.5-sonnet", "openai/gpt-4o-mini", "google/gemini-2.5-flash"],
  custom: ["custom-model"],
};

export function ForecastModal() {
  const modal = useUiStore((state) => state.modal);
  const closeModal = useUiStore((state) => state.closeModal);
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
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [maxFolds, setMaxFolds] = useState(5);
  const [metricFocus, setMetricFocus] = useState<"balanced" | "wmape" | "smape" | "rmse">("balanced");
  const [gbmDepth, setGbmDepth] = useState(3);
  const [llmProvider, setLlmProvider] = useState<string>("openai");
  const [llmApiKey, setLlmApiKey] = useState<string>("");
  const [llmModel, setLlmModel] = useState<string>("gpt-4o-mini");
  const [llmBaseUrl, setLlmBaseUrl] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  const { data: dataset } = useDataset(datasetId || null);

  useEffect(() => {
    try {
      const saved = localStorage.getItem("forecast_hub_llm_config");
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed.provider) setLlmProvider(parsed.provider);
        if (parsed.apiKey) setLlmApiKey(parsed.apiKey);
        if (parsed.model) setLlmModel(parsed.model);
        if (parsed.baseUrl) setLlmBaseUrl(parsed.baseUrl);
      }
    } catch {}
  }, []);

  function updateLlmConfig(provider: string, apiKey: string, model: string, baseUrl: string) {
    setLlmProvider(provider);
    setLlmApiKey(apiKey);
    setLlmModel(model);
    setLlmBaseUrl(baseUrl);
    try {
      localStorage.setItem(
        "forecast_hub_llm_config",
        JSON.stringify({ provider, apiKey, model, baseUrl }),
      );
    } catch {}
  }

  const progress = useForecastProgress(activeRunId, (event) => {
    if (event.status === "completed") {
      setRunId(event.run_id);
      refreshDashboard();
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
  }, [dataset]);

  useEffect(() => {
    if (!open) {
      setError(null);
      startMutation.reset();
    }
  }, [open]);

  function handleRun() {
    if (!datasetId) {
      setError("Choose a dataset to forecast.");
      return;
    }
    setError(null);

    let metricWeights: Record<string, number> | undefined = undefined;
    if (metricFocus === "wmape") metricWeights = { wmape: 0.7, smape: 0.2, rmse: 0.1 };
    else if (metricFocus === "smape") metricWeights = { wmape: 0.2, smape: 0.7, rmse: 0.1 };
    else if (metricFocus === "rmse") metricWeights = { wmape: 0.2, smape: 0.1, rmse: 0.7 };

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
        max_folds: maxFolds,
        metric_weights: metricWeights,
        gbm_max_depth: gbmDepth,
        llm_provider: llmProvider || null,
        llm_api_key: llmApiKey.trim() || null,
        llm_model: llmModel.trim() || null,
        llm_base_url: llmBaseUrl.trim() || null,
      },
      {
        onSuccess: (run) => setActiveRun(run.id),
        onError: (mutationError) => setError(mutationError.message),
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

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Run Forecast"
      description="Fits five candidate models, backtests them and selects a winner."
      width="580px"
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
            <Button variant="primary" onClick={handleRun} loading={startMutation.isPending}>
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
            <select
              value={datasetId}
              onChange={(event) => setDatasetId(event.target.value)}
              className="h-8 w-full rounded-input border border-border bg-surface px-2 text-meta text-text-primary focus:border-accent focus:outline-none"
            >
              <option value="">Select a dataset…</option>
              {(datasets ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} ({item.row_count.toLocaleString()} rows)
                </option>
              ))}
            </select>
          </Field>

          <Field label="Run name">
            <Input value={name} onChange={(event) => setName(event.target.value)} />
          </Field>

          <div className="grid grid-cols-3 gap-3">
            <Field label="Frequency" required>
              <select
                value={frequency}
                onChange={(event) => setFrequency(event.target.value as ForecastFrequency)}
                className="h-8 w-full rounded-input border border-border bg-surface px-2 text-meta capitalize text-text-primary focus:border-accent focus:outline-none"
              >
                {FREQUENCIES.map((item) => (
                  <option key={item} value={item} className="capitalize">
                    {item}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Horizon" required>
              <Input
                type="number"
                min={1}
                max={365}
                value={horizon}
                onChange={(event) => setHorizon(Number(event.target.value) || 1)}
              />
            </Field>

            <Field label="Confidence %" hint="Interval width">
              <Input
                type="number"
                min={51}
                max={99}
                value={confidence}
                onChange={(event) => setConfidence(Number(event.target.value) || 80)}
              />
            </Field>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <Field label="Region column">
              <DimensionSelect
                value={regionColumn}
                onChange={setRegionColumn}
                options={dimensions.map((column) => column.name)}
              />
            </Field>
            <Field label="Category column">
              <DimensionSelect
                value={categoryColumn}
                onChange={setCategoryColumn}
                options={dimensions.map((column) => column.name)}
              />
            </Field>
            <Field label="Weight column" hint="For weighted MAPE">
              <DimensionSelect
                value={weightColumn}
                onChange={setWeightColumn}
                options={numerics.map((column) => column.name)}
              />
            </Field>
          </div>

          <div className="pt-1">
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="text-caption font-medium text-accent hover:underline focus:outline-none"
            >
              {showAdvanced ? "– Hide Advanced Model Settings" : "+ Show Advanced Model Settings"}
            </button>
          </div>

          {showAdvanced ? (
            <div className="space-y-3 rounded-card border border-border bg-surface-muted/30 p-3">
              <div className="grid grid-cols-3 gap-3">
                <Field label="Validation Folds" hint="1 to 10">
                  <Input
                    type="number"
                    min={1}
                    max={10}
                    value={maxFolds}
                    onChange={(e) => setMaxFolds(Number(e.target.value) || 5)}
                  />
                </Field>

                <Field label="Metric Emphasis" hint="Scoring weights">
                  <select
                    value={metricFocus}
                    onChange={(e) => setMetricFocus(e.target.value as any)}
                    className="h-8 w-full rounded-input border border-border bg-surface px-2 text-meta text-text-primary focus:border-accent focus:outline-none"
                  >
                    <option value="balanced">Balanced (Default)</option>
                    <option value="wmape">wMAPE Focus (70%)</option>
                    <option value="smape">sMAPE Focus (70%)</option>
                    <option value="rmse">RMSE Focus (70%)</option>
                  </select>
                </Field>

                <Field label="GBM Max Depth" hint="Tree depth">
                  <Input
                    type="number"
                    min={1}
                    max={10}
                    value={gbmDepth}
                    onChange={(e) => setGbmDepth(Number(e.target.value) || 3)}
                  />
                </Field>
              </div>
            </div>
          ) : null}

          <div className="space-y-3 rounded-card border border-border bg-surface-muted/30 p-3">
            <p className="text-caption font-semibold text-text-primary">
              AI Insights LLM Provider (Optional Frontend Config)
            </p>
            <div className="grid grid-cols-3 gap-3">
              <Field label="LLM Provider">
                <select
                  value={llmProvider}
                  onChange={(e) => {
                    const p = e.target.value;
                    const defaultModel = PROVIDER_MODELS[p]?.[0] ?? "gpt-4o-mini";
                    updateLlmConfig(p, llmApiKey, defaultModel, llmBaseUrl);
                  }}
                  className="h-8 w-full rounded-input border border-border bg-surface px-2 text-meta capitalize text-text-primary focus:border-accent focus:outline-none"
                >
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic (Claude)</option>
                  <option value="groq">Groq</option>
                  <option value="xai">xAI (Grok)</option>
                  <option value="gemini">Google Gemini</option>
                  <option value="openrouter">OpenRouter</option>
                  <option value="custom">Custom / Ollama</option>
                </select>
              </Field>

              <Field label="API Key" hint="Saved in Browser">
                <Input
                  type="password"
                  placeholder="sk-..."
                  value={llmApiKey}
                  onChange={(e) => updateLlmConfig(llmProvider, e.target.value, llmModel, llmBaseUrl)}
                />
              </Field>

              <Field label="LLM Model">
                {PROVIDER_MODELS[llmProvider] ? (
                  <select
                    value={llmModel}
                    onChange={(e) => updateLlmConfig(llmProvider, llmApiKey, e.target.value, llmBaseUrl)}
                    className="h-8 w-full rounded-input border border-border bg-surface px-2 text-meta text-text-primary focus:border-accent focus:outline-none"
                  >
                    {PROVIDER_MODELS[llmProvider].map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                ) : (
                  <Input
                    placeholder="model-name"
                    value={llmModel}
                    onChange={(e) => updateLlmConfig(llmProvider, llmApiKey, e.target.value, llmBaseUrl)}
                  />
                )}
              </Field>
            </div>

            {llmProvider === "custom" || llmProvider === "openrouter" ? (
              <Field label="Custom Base URL" hint="e.g. http://localhost:11434/v1">
                <Input
                  placeholder="https://..."
                  value={llmBaseUrl}
                  onChange={(e) => updateLlmConfig(llmProvider, llmApiKey, llmModel, e.target.value)}
                />
              </Field>
            ) : null}
          </div>

          {error ? <p className="text-caption text-negative">{error}</p> : null}
        </div>
      )}
    </Modal>
  );
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
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="h-8 w-full rounded-input border border-border bg-surface px-2 text-meta text-text-primary focus:border-accent focus:outline-none"
    >
      <option value={NONE}>None</option>
      {options.map((name) => (
        <option key={name} value={name}>
          {name}
        </option>
      ))}
    </select>
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
        <div className="flex items-start gap-2 rounded-card border border-[#f0cdcc] bg-negative-soft px-3 py-2">
          <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0 text-negative" aria-hidden />
          <p className="text-caption text-negative">{progress.error}</p>
        </div>
      ) : null}

      {done ? (
        <p className="rounded-card border border-[#cfe6d9] bg-positive-soft px-3 py-2 text-caption text-positive">
          Forecast complete. The dashboard now reflects this run.
        </p>
      ) : null}
    </div>
  );
}

export { humanizeModel };
