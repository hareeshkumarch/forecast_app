"use client";


import { Monitor, Moon, Rows3, Rows4, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { Button, Field, Input, Select } from "@/components/ui/primitives";
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
      <div role="radiogroup" aria-label={label} className="flex gap-1 rounded-input border border-border bg-surface-muted p-0.5">
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
                "flex flex-1 items-center justify-center gap-1.5 rounded-[7px] px-2 py-1.5",
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

/**
 * Home for settings that belong to the browser rather than to a single run —
 * the LLM credentials used to reword insights, which previously sat in the
 * middle of the Run Forecast dialog.
 */
export function SettingsModal() {
  const modal = useUiStore((state) => state.modal);
  const closeModal = useUiStore((state) => state.closeModal);
  const open = modal === "settings";

  const theme = usePrefsStore((state) => state.theme);
  const density = usePrefsStore((state) => state.density);
  const setTheme = usePrefsStore((state) => state.setTheme);
  const setDensity = usePrefsStore((state) => state.setDensity);

  const [config, setConfig] = useState<LlmConfig>(EMPTY_LLM_CONFIG);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (open) {
      setConfig(loadLlmConfig());
      setSaved(false);
    }
  }, [open]);

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
    <Modal
      open={open}
      onClose={closeModal}
      title="Settings"
      description="Stored in this browser only."
      footer={
        <>
          <Button variant="ghost" onClick={handleClear}>
            Clear
          </Button>
          <Button variant="primary" onClick={handleSave}>
            {saved ? "Saved" : "Save"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <section className="space-y-3">
          <h3 className="eyebrow">Appearance</h3>
          <SegmentedControl label="Theme" value={theme} options={THEMES} onChange={setTheme} />
          <SegmentedControl
            label="Density"
            value={density}
            options={DENSITIES}
            onChange={setDensity}
          />
        </section>

        <section>
          <h3 className="eyebrow">API</h3>
          <div className="mt-2 flex items-center justify-between gap-3 rounded-card border border-border bg-surface-muted px-3 py-2">
            <span className="text-caption text-text-secondary">Backend</span>
            <code className="truncate text-caption text-text-primary">{API_BASE_URL}</code>
          </div>
          <p className="mt-1 text-caption text-text-muted">
            Set at build time by NEXT_PUBLIC_API_BASE_URL.
          </p>
        </section>

        <section>
          <h3 className="eyebrow">Insight rewriter</h3>
          <p className="mt-1.5 text-caption text-text-muted">
            Optional. Every figure in an insight is computed by the backend either way — an LLM
            only rewords the explanation. Leave the key blank to use the server&apos;s own
            configuration.
          </p>

          <div className="mt-2.5 space-y-3">
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
                  <Select
                    value={config.model}
                    onChange={(event) => update({ model: event.target.value })}
                    
                  >
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

            <Field label="API key" hint="Kept in this browser's local storage and sent with a run.">
              <Input
                type="password"
                autoComplete="new-password"
                value={config.apiKey}
                onChange={(event) => update({ apiKey: event.target.value })}
                placeholder="sk-…"
              />
            </Field>

            {PROVIDERS_NEEDING_BASE_URL.has(config.provider) ? (
              <Field label="Base URL" hint="e.g. http://localhost:11434/v1">
                <Input
                  value={config.baseUrl}
                  onChange={(event) => update({ baseUrl: event.target.value })}
                  placeholder="https://…"
                />
              </Field>
            ) : null}
          </div>
        </section>
      </div>
    </Modal>
  );
}
