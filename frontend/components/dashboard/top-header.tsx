"use client";


import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import * as Popover from "@radix-ui/react-popover";
import {
  Bell,
  Calendar,
  ChevronDown,
  Download,
  HelpCircle,
  Settings,
  TrendingUp,
} from "lucide-react";

import { Button, IconButton } from "@/components/ui/primitives";
import { downloadExport, useSummary } from "@/hooks/use-dashboard";
import { formatDateRange } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import type { ExportFormat, ForecastView } from "@/types/api";

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

const VIEWS: ViewOption[] = [
  DEFAULT_VIEW,
  { value: "best", label: "Best Case", description: "Upper 95% scenario" },
  { value: "worst", label: "Worst Case", description: "Lower 95% scenario" },
];

const EXPORT_FORMATS: { value: ExportFormat; label: string; hint: string }[] = [
  { value: "csv", label: "CSV", hint: "Forecast series" },
  { value: "xlsx", label: "Excel", hint: "All sheets" },
  { value: "json", label: "JSON", hint: "Full run detail" },
];


const RANGE_PRESETS = [
  { label: "Full forecast horizon", months: null },
  { label: "Next 3 periods", months: 3 },
  { label: "Next 6 periods", months: 6 },
  { label: "Next 12 periods", months: 12 },
] as const;

const MENU_CONTENT =
  "z-50 min-w-[180px] rounded-card border border-border bg-surface p-1 shadow-popover";

export function TopHeader() {
  const view = useUiStore((state) => state.view);
  const setView = useUiStore((state) => state.setView);
  const rangeStart = useUiStore((state) => state.rangeStart);
  const rangeEnd = useUiStore((state) => state.rangeEnd);
  const setRange = useUiStore((state) => state.setRange);

  const { data: summary } = useSummary();
  const runId = summary?.run_id ?? null;

  const activeView = VIEWS.find((item) => item.value === view) ?? DEFAULT_VIEW;
  const rangeLabel =
    rangeStart || rangeEnd
      ? formatDateRange(rangeStart, rangeEnd)
      : formatDateRange(summary?.range_start ?? null, summary?.range_end ?? null);

  function applyPreset(months: number | null) {
    if (months === null || !summary?.range_start) {
      setRange(null, null);
      return;
    }
    const start = new Date(`${summary.range_start}T00:00:00Z`);
    const end = new Date(start);
    
    end.setUTCMonth(end.getUTCMonth() + months - 1);
    setRange(summary.range_start, end.toISOString().slice(0, 10));
  }

  return (
    <header className="flex h-header shrink-0 items-center gap-4 border-b border-border bg-surface px-5">
      
      <div className="flex items-center gap-2.5">
        <span
          className="flex h-8 w-8 items-center justify-center rounded-[9px] bg-accent"
          aria-hidden
        >
          <TrendingUp className="h-4 w-4 text-white" />
        </span>
        <h1 className="text-title font-semibold tracking-[-0.01em] text-text-primary">
          Forecasting Dashboard
        </h1>
      </div>

      <div className="ml-auto flex items-center gap-2">
        
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button
              type="button"
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-input border border-border bg-surface px-2.5",
                "text-meta font-medium text-text-primary",
                "transition-colors duration-fast hover:bg-surface-muted hover:border-border-strong",
              )}
            >
              {activeView.label}
              <ChevronDown className="h-3.5 w-3.5 text-text-muted" aria-hidden />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content align="end" sideOffset={6} className={MENU_CONTENT}>
              {VIEWS.map((item) => (
                <DropdownMenu.Item
                  key={item.value}
                  onSelect={() => setView(item.value)}
                  className={cn(
                    "cursor-pointer rounded-chip px-2 py-1.5 text-meta outline-none",
                    "data-[highlighted]:bg-surface-muted",
                    item.value === view ? "text-accent" : "text-text-primary",
                  )}
                >
                  <span className="font-medium">{item.label}</span>
                  <span className="block text-caption text-text-muted">{item.description}</span>
                </DropdownMenu.Item>
              ))}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>

        
        <Popover.Root>
          <Popover.Trigger asChild>
            <button
              type="button"
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-input border border-border bg-surface px-2.5",
                "text-meta text-text-primary",
                "transition-colors duration-fast hover:bg-surface-muted hover:border-border-strong",
              )}
            >
              <Calendar className="h-3.5 w-3.5 text-text-muted" aria-hidden />
              {rangeLabel}
              <ChevronDown className="h-3.5 w-3.5 text-text-muted" aria-hidden />
            </button>
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content
              align="end"
              sideOffset={6}
              className="z-50 w-[248px] rounded-card border border-border bg-surface p-2 shadow-popover"
            >
              <p className="px-1.5 pb-1.5 text-caption font-medium text-text-muted">
                Forecast window
              </p>
              <div className="space-y-0.5">
                {RANGE_PRESETS.map((preset) => (
                  <button
                    key={preset.label}
                    type="button"
                    onClick={() => applyPreset(preset.months)}
                    className="w-full rounded-chip px-1.5 py-1.5 text-left text-meta text-text-primary transition-colors duration-fast hover:bg-surface-muted"
                  >
                    {preset.label}
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
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>

        <span className="mx-0.5 h-5 w-px bg-border" aria-hidden />

        <IconButton label="Notifications" icon={Bell} />
        <IconButton label="Help and documentation" icon={HelpCircle} />

        
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <Button variant="secondary" size="md" icon={Download} disabled={!runId}>
              Export
              <ChevronDown className="h-3.5 w-3.5 text-text-muted" aria-hidden />
            </Button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content align="end" sideOffset={6} className={MENU_CONTENT}>
              {EXPORT_FORMATS.map((format) => (
                <DropdownMenu.Item
                  key={format.value}
                  disabled={!runId}
                  onSelect={() => runId && downloadExport(runId, format.value)}
                  className={cn(
                    "flex cursor-pointer items-center gap-2 rounded-chip px-2 py-1.5 text-meta text-text-primary outline-none",
                    "data-[highlighted]:bg-surface-muted data-[disabled]:cursor-not-allowed data-[disabled]:text-text-muted",
                  )}
                >
                  <span className="font-medium">{format.label}</span>
                  <span className="ml-auto text-caption text-text-muted">{format.hint}</span>
                </DropdownMenu.Item>
              ))}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>

        <IconButton label="Settings" icon={Settings} />
      </div>
    </header>
  );
}
