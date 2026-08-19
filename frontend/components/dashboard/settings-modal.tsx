"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Database,
  Monitor,
  Moon,
  Rows3,
  Rows4,
  ShieldCheck,
  Sun,
  XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { Badge, Button, Card, Field, Input, Skeleton } from "@/components/ui/primitives";
import { ProviderLogo, providerMark } from "@/components/ui/provider-logo";
import { Select } from "@/components/ui/select";
import { useCheckLlm, useHealth } from "@/hooks/use-dashboard";
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
import { useCurrentUser } from "@/hooks/use-dashboard";
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
                "flex min-h-11 flex-1 items-center justify-center gap-1.5 px-2 fine:min-h-8",
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

function StorageCard() {
  const { data, isLoading } = useHealth();

  const onSupabase = data?.database_target === "supabase";
  const fellBack = Boolean(data && data.supabase_configured && !onSupabase);

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="panel-title">Where runs are stored</h2>
          <p className="mt-0.5 text-caption text-text-muted">
            Datasets, forecast runs, series and insights all live here.
          </p>
        </div>
        {data ? (
          <Badge
            tone={onSupabase ? "positive" : fellBack ? "warning" : "neutral"}
            className="shrink-0 whitespace-nowrap"
          >
            {onSupabase ? "Supabase" : "Local"}
          </Badge>
        ) : null}
      </div>

      {isLoading ? (
        <Skeleton className="mt-3 h-14 w-full" />
      ) : data ? (
        <>
          <div className="mt-3 flex items-start gap-2 rounded-card border border-border bg-surface-muted px-3 py-2.5">
            <Database className="mt-0.5 h-3.5 w-3.5 shrink-0 text-text-muted" aria-hidden />
            <code className="min-w-0 break-all text-caption text-text-primary">
              {data.database_host}
            </code>
          </div>

          {fellBack ? (
            <p className="mt-2 flex items-start gap-1.5 text-caption text-warning">
              <AlertTriangle className="mt-px h-3 w-3 shrink-0" aria-hidden />
              <span>
                Supabase is configured but was unreachable when the API started, so this node is
                writing to its local fallback. Restart the API once Supabase is back.
              </span>
            </p>
          ) : (
            <p className="mt-2 text-caption text-text-muted">
              {onSupabase
                ? "Supabase is the store of record for this deployment."
                : "Set SUPABASE_DB_URL on the API to make Supabase the store of record."}
            </p>
          )}
        </>
      ) : (
        <p className="mt-3 text-caption text-text-muted">The API did not report its store.</p>
      )}
    </Card>
  );
}

function parseRate(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

export function SettingsPanel({ className }: { className?: string }) {
  // The provider key and token rates are one setting for the whole
  // deployment. A member changing them changes them for everybody, which is
  // not a thing a member should be able to do by wandering into Settings.
  // Not signed in is not the same as not permitted. A deployment with no
  // sign-in configured answers `authenticated: false` for everybody, and
  // hiding the provider settings there would leave nowhere to set them at all.
  const { data: me } = useCurrentUser();
  const isAdmin = me === undefined || !me.authenticated || me.is_admin;
  const theme = usePrefsStore((state) => state.theme);
  const density = usePrefsStore((state) => state.density);
  const setTheme = usePrefsStore((state) => state.setTheme);
  const setDensity = usePrefsStore((state) => state.setDensity);

  const [config, setConfig] = useState<LlmConfig>(EMPTY_LLM_CONFIG);
  const [saved, setSaved] = useState(false);
  const check = useCheckLlm();

  useEffect(() => setConfig(loadLlmConfig()), []);

  function update(patch: Partial<LlmConfig>) {
    setConfig((previous) => ({ ...previous, ...patch }));
    setSaved(false);
    check.reset();
  }

  function handleSave() {
    saveLlmConfig(config);
    setSaved(true);
  }

  function handleClear() {
    clearLlmConfig();
    setConfig(EMPTY_LLM_CONFIG);
    setSaved(false);
    check.reset();
  }

  const models = PROVIDER_MODELS[config.provider] ?? [];
  const result = check.data;

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

        {isAdmin ? (
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
        ) : null}

        {isAdmin ? <StorageCard /> : null}
      </div>

      {!isAdmin ? (
        <Card className="p-4">
          <h2 className="panel-title">Everything else here is deployment-wide</h2>
          <p className="mt-1.5 max-w-[60ch] text-caption text-text-muted">
            The language provider, its key and the token rates apply to everybody using this
            deployment, so they are changed by an administrator rather than per person. Nothing
            you do on this page affects anyone else.
          </p>
        </Card>
      ) : (
      <Card className="p-4">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-input bg-accent-soft">
            <ShieldCheck className="h-4 w-4 text-accent" aria-hidden />
          </span>
          <div>
            <h2 className="panel-title">How insights are worded</h2>
            <p className="mt-0.5 max-w-[68ch] text-caption text-text-muted">
              Every figure on this platform is computed here. A provider connected below is only
              ever asked to say those figures in better English — if it changes one, its answer is
              thrown away and the platform&apos;s own wording stands. Your key stays in this
              browser; only token counts, timings and cost are recorded.
            </p>
          </div>
        </div>

        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Provider">
              <Select
                value={config.provider}
                onChange={(provider) => update({ provider, model: defaultModelFor(provider) })}
                options={PROVIDERS.map((provider) => ({
                  value: provider.value,
                  label: provider.label,
                  hint: provider.hint,
                  icon: providerMark(provider.value),
                  iconKeepsColour: true,
                }))}
                menuClassName="min-w-[16rem]"
              />
            </Field>

            <Field label="Model">
              {models.length > 0 ? (
                <Select
                  value={config.model}
                  onChange={(model) => update({ model })}
                  options={models.map((model) => ({ value: model, label: model }))}
                />
              ) : (
                <Input
                  value={config.model}
                  onChange={(event) => update({ model: event.target.value })}
                  placeholder="model-name"
                />
              )}
            </Field>
          </div>

          <Field
            label="API key"
            hint="Kept in this browser and sent with the requests that need it, never stored on the server."
          >
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

          <div className="flex flex-wrap items-center gap-2 rounded-card border border-border bg-surface-muted px-3 py-2.5">
            <ProviderLogo provider={config.provider} className="h-4 w-4" />
            <span className="min-w-0 flex-1 text-caption text-text-secondary">
              {result ? (
                <span
                  className={cn(
                    "flex items-center gap-1.5",
                    result.ok ? "text-positive" : "text-negative",
                  )}
                >
                  {result.ok ? (
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  ) : (
                    <XCircle className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  )}
                  {result.message}
                </span>
              ) : (
                "Check the key before a forecast depends on it."
              )}
            </span>
            <Button
              size="sm"
              loading={check.isPending}
              disabled={!config.apiKey.trim()}
              onClick={() => check.mutate(config)}
            >
              Test connection
            </Button>
          </div>

          <div className="rounded-card border border-border bg-surface-muted p-3">
            <p className="text-meta font-medium text-text-primary">If the provider bills silently</p>
            <p className="mt-0.5 text-caption text-text-muted">
              Some providers return the cost of a request and some do not. Rates entered here are
              used to work it out for the ones that do not.
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
      )}
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
