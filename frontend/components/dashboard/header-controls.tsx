"use client";


import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import * as Popover from "@radix-ui/react-popover";
import { Calendar, ChevronDown, Download, History, SlidersHorizontal } from "lucide-react";

import { MENU_CONTENT, MENU_ITEM } from "@/components/ui/primitives";
import { downloadExport, useForecastRuns, useHealth, useSummary } from "@/hooks/use-dashboard";
import { formatDateRange, formatRelativeTime, humanizeModel } from "@/lib/format";
import { labelGranularity, periodWindowEnd } from "@/lib/periods";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import type { ExportFormat, ForecastRun, ForecastView } from "@/types/api";

interface ViewOption {
  value: ForecastView;
  label: string;
  description: string;
}

const DEFAULT_VIEW: ViewOption = {
  value: "base",
  label: "Base Case",
  description: "Most likely outcome",
};

export const VIEWS: ViewOption[] = [
  DEFAULT_VIEW,
  { value: "best", label: "Best Case", description: "Upper 95% scenario" },
  { value: "worst", label: "Worst Case", description: "Lower 95% scenario" },
];

const EXPORT_FORMATS: { value: ExportFormat; label: string; hint: string }[] = [
  { value: "csv", label: "CSV", hint: "Forecast series" },
  { value: "xlsx", label: "Excel", hint: "All sheets" },
  { value: "json", label: "JSON", hint: "Full run detail" },
];

const PRESET_COUNTS = [3, 6, 12] as const;

const TRIGGER = cn(
  "inline-flex h-8 max-w-[190px] items-center gap-1.5 rounded-input border border-border bg-surface px-2.5",
  "text-meta text-text-primary",
  "transition-colors duration-fast hover:border-border-strong hover:bg-surface-muted",
);

const NATIVE_SELECT =
  "h-8 w-full rounded-input border border-border bg-surface px-2 text-meta text-text-primary focus:border-accent focus:outline-none";

/**
 * The run the dashboard is actually showing: either the one pinned in the
 * store, or whichever one the API fell back to.
 */
export function useActiveRun(): ForecastRun | null {
  const { data: summary } = useSummary();
  const { data: runs } = useForecastRuns();
  return runs?.find((run) => run.id === summary?.run_id) ?? null;
}

function runLabel(run: ForecastRun): string {
  const when = new Date(run.created_at);
  const date = Number.isNaN(when.getTime())
    ? ""
    : when.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return `${run.name}${date ? ` · ${date}` : ""}`;
}


export function RunControl({ className }: { className?: string }) {
  const { data: runs } = useForecastRuns();
  const { data: summary } = useSummary();
  const pinnedRunId = useUiStore((state) => state.runId);
  const setRunId = useUiStore((state) => state.setRunId);

  const completed = (runs ?? []).filter((run) => run.status === "completed");
  const label = pinnedRunId
    ? completed.find((run) => run.id === pinnedRunId)?.name ?? "Selected run"
    : summary?.run_name ?? "Latest run";

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button type="button" className={cn(TRIGGER, className)} disabled={completed.length === 0}>
          <History className="h-3.5 w-3.5 shrink-0 text-text-muted" aria-hidden />
          <span className="truncate">{label}</span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-text-muted" aria-hidden />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={6} className={cn(MENU_CONTENT, "max-w-[280px]")}>
          <DropdownMenu.Item
            onSelect={() => setRunId(null)}
            className={cn(MENU_ITEM, !pinnedRunId && "text-accent")}
          >
            <span className="font-medium">Latest run</span>
            <span className="ml-auto text-caption text-text-muted">Default</span>
          </DropdownMenu.Item>

          {completed.length > 0 ? <div className="my-1 h-px bg-border" /> : null}

          {completed.slice(0, 8).map((run) => (
            <DropdownMenu.Item
              key={run.id}
              onSelect={() => setRunId(run.id)}
              className={cn(MENU_ITEM, run.id === pinnedRunId && "text-accent")}
            >
              <span className="min-w-0 flex-1 truncate">{runLabel(run)}</span>
              <span className="shrink-0 text-caption text-text-muted">
                {humanizeModel(run.selected_model)}
              </span>
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}


export function ScenarioControl({ className }: { className?: string }) {
  const view = useUiStore((state) => state.view);
  const setView = useUiStore((state) => state.setView);
  const active = VIEWS.find((item) => item.value === view) ?? DEFAULT_VIEW;

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button type="button" className={cn(TRIGGER, "font-medium", className)}>
          <span className="truncate">{active.label}</span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-text-muted" aria-hidden />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={6} className={MENU_CONTENT}>
          {VIEWS.map((item) => (
            <DropdownMenu.Item
              key={item.value}
              onSelect={() => setView(item.value)}
              className={cn(MENU_ITEM, "block", item.value === view && "text-accent")}
            >
              <span className="font-medium">{item.label}</span>
              <span className="block text-caption text-text-muted">{item.description}</span>
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}


export function RangeControl({ className }: { className?: string }) {
  const rangeStart = useUiStore((state) => state.rangeStart);
  const rangeEnd = useUiStore((state) => state.rangeEnd);
  const { data: summary } = useSummary();
  const run = useActiveRun();

  const granularity = labelGranularity(run?.frequency);
  const label =
    rangeStart || rangeEnd
      ? formatDateRange(rangeStart, rangeEnd, granularity)
      : formatDateRange(summary?.range_start ?? null, summary?.range_end ?? null, granularity);

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button type="button" className={cn(TRIGGER, className)}>
          <Calendar className="h-3.5 w-3.5 shrink-0 text-text-muted" aria-hidden />
          <span className="truncate">{label}</span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-text-muted" aria-hidden />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={6}
          collisionPadding={8}
          className="z-50 w-[260px] max-w-[calc(100vw-16px)] rounded-card border border-border bg-surface p-2 shadow-popover"
        >
          <RangeFields />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

/** Shared by the desktop popover and the compact filters sheet. */
export function RangeFields() {
  const rangeStart = useUiStore((state) => state.rangeStart);
  const rangeEnd = useUiStore((state) => state.rangeEnd);
  const setRange = useUiStore((state) => state.setRange);
  const { data: summary } = useSummary();
  const run = useActiveRun();

  const frequency = run?.frequency ?? "monthly";
  const unit = frequency === "monthly" ? "months" : frequency === "daily" ? "days" : frequency === "weekly" ? "weeks" : "quarters";

  function applyPreset(count: number | null) {
    if (count === null || !summary?.range_start) {
      setRange(null, null);
      return;
    }
    setRange(summary.range_start, periodWindowEnd(summary.range_start, count, frequency));
  }

  return (
    <>
      <p className="px-1.5 pb-1.5 text-caption font-medium text-text-muted">Forecast window</p>
      <div className="space-y-0.5">
        <button
          type="button"
          onClick={() => applyPreset(null)}
          className="w-full rounded-chip px-1.5 py-1.5 text-left text-meta text-text-primary transition-colors duration-fast hover:bg-surface-muted"
        >
          Full forecast horizon
        </button>
        {PRESET_COUNTS.map((count) => (
          <button
            key={count}
            type="button"
            onClick={() => applyPreset(count)}
            disabled={!summary?.range_start}
            className="w-full rounded-chip px-1.5 py-1.5 text-left text-meta text-text-primary transition-colors duration-fast hover:bg-surface-muted disabled:text-text-muted"
          >
            {`Next ${count} ${unit}`}
          </button>
        ))}
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 border-t border-border pt-2">
        <label className="block">
          <span className="mb-1 block text-caption text-text-muted">From</span>
          <input
            type="date"
            value={rangeStart ?? ""}
            onChange={(event) => setRange(event.target.value || null, rangeEnd)}
            className="h-7 w-full rounded-input border border-border bg-surface px-1.5 text-caption text-text-primary focus:border-accent focus:outline-none"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-caption text-text-muted">To</span>
          <input
            type="date"
            value={rangeEnd ?? ""}
            onChange={(event) => setRange(rangeStart, event.target.value || null)}
            className="h-7 w-full rounded-input border border-border bg-surface px-1.5 text-caption text-text-primary focus:border-accent focus:outline-none"
          />
        </label>
      </div>
    </>
  );
}


/**
 * One button standing in for the run / scenario / window trio on viewports
 * too narrow to line them up. Native controls inside, which phones render as
 * their own pickers.
 */
export function CompactFilters() {
  const view = useUiStore((state) => state.view);
  const setView = useUiStore((state) => state.setView);
  const pinnedRunId = useUiStore((state) => state.runId);
  const setRunId = useUiStore((state) => state.setRunId);
  const { data: runs } = useForecastRuns();

  const completed = (runs ?? []).filter((run) => run.status === "completed");

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button type="button" aria-label="Filters" title="Filters" className={cn(TRIGGER, "px-2")}>
          <SlidersHorizontal className="h-4 w-4 text-text-secondary" aria-hidden />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={6}
          collisionPadding={8}
          className="z-50 w-[290px] max-w-[calc(100vw-16px)] space-y-3 rounded-card border border-border bg-surface p-3 shadow-popover"
        >
          <label className="block">
            <span className="mb-1 block text-caption font-medium text-text-secondary">
              Forecast run
            </span>
            <select
              value={pinnedRunId ?? ""}
              onChange={(event) => setRunId(event.target.value || null)}
              className={NATIVE_SELECT}
            >
              <option value="">Latest run</option>
              {completed.map((run) => (
                <option key={run.id} value={run.id}>
                  {runLabel(run)}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-caption font-medium text-text-secondary">Scenario</span>
            <select
              value={view}
              onChange={(event) => setView(event.target.value as ForecastView)}
              className={NATIVE_SELECT}
            >
              {VIEWS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <div className="border-t border-border pt-1">
            <RangeFields />
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}


export function ExportControl() {
  const { data: summary } = useSummary();
  const runId = summary?.run_id ?? null;

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          aria-label="Export"
          title={runId ? "Export this run" : "Run a forecast to enable exports"}
          disabled={!runId}
          className={cn(TRIGGER, "gap-1.5 px-2 disabled:opacity-60 sm:px-2.5")}
        >
          <Download className="h-4 w-4 shrink-0 text-text-secondary" aria-hidden />
          <span className="hidden sm:inline">Export</span>
          <ChevronDown className="hidden h-3.5 w-3.5 text-text-muted sm:block" aria-hidden />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={6} className={MENU_CONTENT}>
          {EXPORT_FORMATS.map((format) => (
            <DropdownMenu.Item
              key={format.value}
              disabled={!runId}
              onSelect={() => runId && downloadExport(runId, format.value)}
              className={MENU_ITEM}
            >
              <span className="font-medium">{format.label}</span>
              <span className="ml-auto text-caption text-text-muted">{format.hint}</span>
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}


/** Live API health, in place of a decorative bell. */
export function StatusControl() {
  const { data, isLoading, isError, dataUpdatedAt } = useHealth();

  const tone = isError
    ? { dot: "bg-negative", label: "Offline" }
    : isLoading
      ? { dot: "bg-border-strong", label: "Checking" }
      : data?.status === "ok"
        ? { dot: "bg-positive", label: "Healthy" }
        : { dot: "bg-warning", label: "Degraded" };

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          aria-label={`API status: ${tone.label}`}
          title={`API status: ${tone.label}`}
          className={cn(TRIGGER, "gap-1.5 px-2 sm:px-2.5")}
        >
          <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", tone.dot)} aria-hidden />
          <span className="hidden sm:inline">{tone.label}</span>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={6}
          collisionPadding={8}
          className="z-50 w-[260px] max-w-[calc(100vw-16px)] rounded-card border border-border bg-surface p-3 shadow-popover"
        >
          <p className="text-caption font-semibold text-text-primary">API status</p>

          {isError ? (
            <p className="mt-1.5 text-caption text-negative">
              The API is not reachable. Start the backend, then reload.
            </p>
          ) : (
            <dl className="mt-2 space-y-1.5">
              <StatusRow label="Service" value={data?.status ?? "…"} />
              <StatusRow label="Database" value={data?.database ?? "…"} />
              <StatusRow
                label="Storage"
                value={data ? (data.storage_writable ? "writable" : "read-only") : "…"}
              />
              <StatusRow label="Forecast workers" value={data ? String(data.forecast_workers) : "…"} />
              <StatusRow label="Upload limit" value={data ? `${data.max_upload_mb} MB` : "…"} />
              <StatusRow
                label="Checked"
                value={dataUpdatedAt ? formatRelativeTime(new Date(dataUpdatedAt).toISOString()) : "…"}
              />
            </dl>
          )}

          {data?.using_default_credential_key ? (
            <p className="mt-2 rounded-chip border border-[#eddcbc] bg-warning-soft px-2 py-1.5 text-caption text-warning">
              Connector credentials are encrypted with the default development
              key. Set CREDENTIAL_SECRET_KEY before storing anything real.
            </p>
          ) : null}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-caption text-text-secondary">{label}</dt>
      <dd className="truncate text-caption font-medium text-text-primary">{value}</dd>
    </div>
  );
}
