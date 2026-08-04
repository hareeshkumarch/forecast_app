"use client";

import { Monitor, Moon, Rows3, Rows4, ShieldCheck, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { Button, Card, Field, Input, Select } from "@/components/ui/primitives";
import { API_BASE_URL } from "@/lib/api";
import {
  EMPTY_LLM_CONFIG,
  PROVIDERS,
  PROVIDERS_NEEDING_BASE_URL,
  PROVIDER_MODELS,
  clearLlmConfig,
  defaultModelFor,
  loadLlmConfig,
  saveLlmConfig,
  type LlmConfig,
} from "@/lib/llm-config";
import { cn } from "@/lib/utils";
import { usePrefsStore, type Density, type ThemeChoice } from "@/stores/prefs-store";
import { useUiStore } from "@/stores/ui-store";

const THEMES: { value: ThemeChoice; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

const DENSITIES: { value: Density; label: string; icon: typeof Rows3 }[] = [
  { value: "comfortable", label: "Comfortable", icon: Rows3 },
  { value: "compact", label: "Compact", icon: Rows4 },
];

function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string; icon: typeof Sun }[];
  onChange: (next: T) => void;
}) {
  return (
    <div>
      <span className="mb-1 block text-caption font-medium text-text-secondary">{label}</span>
      <div
        role="radiogroup"
        aria-label={label}
        className="flex gap-1 rounded-input border border-border bg-surface-muted p-0.5"
      >
        {options.map((option) => {
          const Icon = option.icon;
          const active = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange(option.value)}
              className={cn(
                "flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-[7px] px-2 sm:min-h-8",
                "text-meta font-medium transition-colors duration-fast",
                active
                  ? "bg-surface text-text-primary shadow-card"
                  : "text-text-secondary hover:text-text-primary",
              )}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden />
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function parseRate(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

export function SettingsPanel({ className }: { className?: string }) {
  const theme = usePrefsStore((state) => state.theme);
  const density = usePrefsStore((state) => state.density);
  const setTheme = usePrefsStore((state) => state.setTheme);
  const setDensity = usePrefsStore((state) => state.setDensity);

  const [config, setConfig] = useState<LlmConfig>(EMPTY_LLM_CONFIG);
  const [saved, setSaved] = useState(false);

  useEffect(() => setConfig(loadLlmConfig()), []);

  function update(patch: Partial<LlmConfig>) {
    setConfig((previous) => ({ ...previous, ...patch }));
    setSaved(false);
  }

  function handleSave() {
    saveLlmConfig(config);
    setSaved(true);
  }

  function handleClear() {
    clearLlmConfig();
    setConfig(EMPTY_LLM_CONFIG);
    setSaved(false);
  }

  const models = PROVIDER_MODELS[config.provider] ?? [];

  return (
    <div className={cn("grid gap-4 xl:grid-cols-[minmax(260px,0.72fr)_minmax(0,1.28fr)]", className)}>
      <div className="space-y-4">
        <Card className="p-4">
          <h2 className="panel-title">Appearance</h2>
          <p className="mt-0.5 text-caption text-text-muted">Personal to this browser.</p>
          <div className="mt-4 space-y-3">
            <SegmentedControl label="Theme" value={theme} options={THEMES} onChange={setTheme} />
            <SegmentedControl
              label="Density"
              value={density}
              options={DENSITIES}
              onChange={setDensity}
            />
          </div>
        </Card>

        <Card className="p-4">
          <h2 className="panel-title">Application API</h2>
          <div className="mt-3 rounded-card border border-border bg-surface-muted px-3 py-2.5">
            <span className="text-caption text-text-secondary">Backend</span>
            <code className="mt-1 block break-all text-caption text-text-primary">{API_BASE_URL}</code>
          </div>
          <p className="mt-2 text-caption text-text-muted">
            Configured at build time with NEXT_PUBLIC_API_BASE_URL.
          </p>
        </Card>
      </div>

      <Card className="p-4">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-input bg-accent-soft">
            <ShieldCheck className="h-4 w-4 text-accent" aria-hidden />
          </span>
          <div>
            <h2 className="panel-title">Insight rewriter and pricing</h2>
            <p className="mt-0.5 max-w-[68ch] text-caption text-text-muted">
              Forecast numbers are computed by the platform. The LLM only rewrites explanations.
              Token, latency, outcome, and cost metadata are recorded without prompts or API keys.
            </p>
          </div>
        </div>

        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Provider">
              <Select
                value={config.provider}
                onChange={(event) => {
                  const provider = event.target.value;
                  update({ provider, model: defaultModelFor(provider) });
                }}
              >
                {PROVIDERS.map((provider) => (
                  <option key={provider.value} value={provider.value}>
                    {provider.label}
                  </option>
                ))}
              </Select>
            </Field>

            <Field label="Model">
              {models.length > 0 ? (
                <Select value={config.model} onChange={(event) => update({ model: event.target.value })}>
                  {models.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input
                  value={config.model}
                  onChange={(event) => update({ model: event.target.value })}
                  placeholder="model-name"
                />
              )}
            </Field>
          </div>

          <Field label="API key" hint="Stored in this browser and sent only when starting a run.">
            <Input
              type="password"
              autoComplete="new-password"
              value={config.apiKey}
              onChange={(event) => update({ apiKey: event.target.value })}
              placeholder="Provider API key"
            />
          </Field>

          {PROVIDERS_NEEDING_BASE_URL.has(config.provider) ? (
            <Field label="Base URL" hint="For example, http://localhost:11434/v1">
              <Input
                value={config.baseUrl}
                onChange={(event) => update({ baseUrl: event.target.value })}
                placeholder="https://provider.example/v1"
              />
            </Field>
          ) : null}

          <div className="rounded-card border border-border bg-surface-muted p-3">
            <p className="text-meta font-medium text-text-primary">Cost fallback</p>
            <p className="mt-0.5 text-caption text-text-muted">
              Optional USD rates per one million tokens, used only when the provider does not
              return a cost.
            </p>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Input token rate">
                <Input
                  type="number"
                  min="0"
                  step="0.01"
                  value={config.inputCostPerMillion ?? ""}
                  onChange={(event) => update({ inputCostPerMillion: parseRate(event.target.value) })}
                  placeholder="0.00"
                />
              </Field>
              <Field label="Output token rate">
                <Input
                  type="number"
                  min="0"
                  step="0.01"
                  value={config.outputCostPerMillion ?? ""}
                  onChange={(event) => update({ outputCostPerMillion: parseRate(event.target.value) })}
                  placeholder="0.00"
                />
              </Field>
            </div>
          </div>

          <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4">
            <Button variant="ghost" onClick={handleClear}>Clear</Button>
            <Button variant="primary" onClick={handleSave}>{saved ? "Saved" : "Save settings"}</Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

export function SettingsModal() {
  const modal = useUiStore((state) => state.modal);
  const closeModal = useUiStore((state) => state.closeModal);
  return (
    <Modal
      open={modal === "settings"}
      onClose={closeModal}
      title="Settings"
      description="Appearance, providers, and usage pricing."
      size="lg"
    >
      <SettingsPanel />
    </Modal>
  );
}
