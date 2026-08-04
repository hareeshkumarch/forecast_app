"use client";

import * as Dialog from "@radix-ui/react-dialog";
import * as VisuallyHidden from "@radix-ui/react-visually-hidden";
import {
  BookOpen,
  Activity,
  Database,
  Download,
  FileBarChart2,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Rows3,
  Search,
  Settings,
  Sparkles,
  Sun,
  TrendingUp,
  Upload,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { downloadExport, useSummary } from "@/hooks/use-dashboard";
import { API_BASE_URL } from "@/lib/api";
import { cn } from "@/lib/utils";
import { usePrefsStore } from "@/stores/prefs-store";
import { useUiStore } from "@/stores/ui-store";
import type { ForecastView } from "@/types/api";

interface Command {
  id: string;
  label: string;
  hint?: string;
  group: string;
  icon: LucideIcon;
  keywords?: string;
  run: () => void;
}

/** Matches on the label, the group and any extra keywords, in order typed. */
function matches(command: Command, query: string): boolean {
  if (!query) return true;
  const haystack = `${command.label} ${command.group} ${command.keywords ?? ""}`.toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .every((token) => haystack.includes(token));
}

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const router = useRouter();
  const listRef = useRef<HTMLDivElement>(null);

  const openModal = useUiStore((state) => state.openModal);
  const setView = useUiStore((state) => state.setView);
  const setRunId = useUiStore((state) => state.setRunId);
  const toggleTheme = usePrefsStore((state) => state.toggleTheme);
  const density = usePrefsStore((state) => state.density);
  const setDensity = usePrefsStore((state) => state.setDensity);
  const resolvedTheme = usePrefsStore((state) => state.resolvedTheme);
  const sidebarCollapsed = usePrefsStore((state) => state.sidebarCollapsed);
  const toggleSidebar = usePrefsStore((state) => state.toggleSidebar);

  const { data: summary } = useSummary();
  const runId = summary?.run_id ?? null;

  const commands = useMemo<Command[]>(() => {
    const scenario = (view: ForecastView, label: string): Command => ({
      id: `view-${view}`,
      label: `Switch to ${label}`,
      group: "Scenario",
      icon: TrendingUp,
      keywords: "case scenario view",
      run: () => setView(view),
    });

    return [
      {
        id: "new-forecast",
        label: "New forecast",
        hint: "N",
        group: "Actions",
        icon: Plus,
        keywords: "run model fit",
        run: () => openModal("configure-forecast"),
      },
      {
        id: "upload",
        label: "Upload dataset",
        hint: "U",
        group: "Actions",
        icon: Upload,
        keywords: "csv xlsx import file",
        run: () => openModal("upload-dataset"),
      },
      {
        id: "add-connector",
        label: "Add connector",
        group: "Actions",
        icon: Database,
        keywords: "source database warehouse",
        run: () => openModal("add-connector"),
      },
      {
        id: "connectors",
        label: "Browse data connectors",
        group: "Navigate",
        icon: Database,
        run: () => router.push("/connectors"),
      },
      {
        id: "reports",
        label: "Open forecast reports",
        group: "Navigate",
        icon: FileBarChart2,
        run: () => router.push("/reports"),
      },
      {
        id: "usage",
        label: "Open LLM usage",
        group: "Navigate",
        icon: Activity,
        keywords: "tokens requests cost latency",
        run: () => router.push("/usage"),
      },
      {
        id: "insights",
        label: "View all insights",
        hint: "I",
        group: "Navigate",
        icon: Sparkles,
        run: () => openModal("all-insights"),
      },
      {
        id: "model",
        label: "Model selection detail",
        group: "Navigate",
        icon: TrendingUp,
        keywords: "candidates backtest accuracy",
        run: () => openModal("model-detail"),
      },
      scenario("base", "base case"),
      scenario("best", "best case"),
      scenario("worst", "worst case"),
      {
        id: "latest-run",
        label: "Show the latest run",
        group: "Scenario",
        icon: TrendingUp,
        keywords: "reset history",
        run: () => setRunId(null),
      },
      ...(runId
        ? (["csv", "xlsx", "json"] as const).map((format) => ({
            id: `export-${format}`,
            label: `Export ${format.toUpperCase()}`,
            group: "Export",
            icon: Download,
            keywords: "download save",
            run: () => downloadExport(runId, format),
          }))
        : []),
      {
        id: "theme",
        label: resolvedTheme === "dark" ? "Switch to light theme" : "Switch to dark theme",
        hint: "T",
        group: "Preferences",
        icon: resolvedTheme === "dark" ? Sun : Moon,
        keywords: "appearance colour color mode",
        run: toggleTheme,
      },
      {
        id: "density",
        label: density === "compact" ? "Use comfortable density" : "Use compact density",
        group: "Preferences",
        icon: Rows3,
        keywords: "spacing rows thickness",
        run: () => setDensity(density === "compact" ? "comfortable" : "compact"),
      },
      {
        id: "sidebar",
        label: sidebarCollapsed ? "Expand the navigation rail" : "Collapse the navigation rail",
        hint: "[",
        group: "Preferences",
        icon: sidebarCollapsed ? PanelLeftOpen : PanelLeftClose,
        keywords: "sidebar nav rail hide show width",
        run: toggleSidebar,
      },
      {
        id: "settings",
        label: "Open settings",
        group: "Preferences",
        icon: Settings,
        run: () => router.push("/settings"),
      },
      {
        id: "docs",
        label: "API documentation",
        group: "Preferences",
        icon: BookOpen,
        keywords: "swagger openapi help",
        run: () => window.open(`${API_BASE_URL}/docs`, "_blank", "noreferrer"),
      },
    ];
  }, [
    density,
    sidebarCollapsed,
    toggleSidebar,
    openModal,
    resolvedTheme,
    router,
    runId,
    setDensity,
    setRunId,
    setView,
    toggleTheme,
  ]);

  const visible = useMemo(
    () => commands.filter((command) => matches(command, query)),
    [commands, query],
  );

  useEffect(() => setCursor(0), [query]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement ||
        target?.isContentEditable;

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((previous) => !previous);
        return;
      }

      if (typing || open || event.metaKey || event.ctrlKey || event.altKey) return;

      const shortcuts: Record<string, () => void> = {
        n: () => openModal("configure-forecast"),
        u: () => openModal("upload-dataset"),
        i: () => openModal("all-insights"),
        t: toggleTheme,
        "?": () => setOpen(true),
      };

      const action = shortcuts[event.key.toLowerCase()];
      if (action) {
        event.preventDefault();
        action();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, openModal, toggleTheme]);

  function runAt(index: number) {
    const command = visible[index];
    if (!command) return;
    setOpen(false);
    setQuery("");
    command.run();
  }

  const grouped = visible.reduce<Record<string, Command[]>>((accumulator, command) => {
    (accumulator[command.group] ??= []).push(command);
    return accumulator;
  }, {});

  let flatIndex = -1;

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuery("");
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[60] bg-overlay backdrop-blur-[1px]" />
        <Dialog.Content
          aria-describedby={undefined}
          className={cn(
            "fixed left-1/2 top-[12%] z-[61] w-[calc(100vw-24px)] max-w-[520px] -translate-x-1/2",
            "overflow-hidden rounded-card border border-border bg-surface shadow-popover focus:outline-none",
          )}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setCursor((previous) => Math.min(previous + 1, visible.length - 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setCursor((previous) => Math.max(previous - 1, 0));
            } else if (event.key === "Enter") {
              event.preventDefault();
              runAt(cursor);
            }
          }}
        >
          <VisuallyHidden.Root>
            <Dialog.Title>Command palette</Dialog.Title>
          </VisuallyHidden.Root>

          <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
            <Search className="h-4 w-4 shrink-0 text-text-muted" aria-hidden />
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search actions…"
              aria-label="Search actions"
              className="w-full bg-transparent text-body text-text-primary placeholder:text-text-muted focus:outline-none"
            />
            <kbd className="hidden shrink-0 rounded-chip border border-border px-1.5 py-0.5 text-micro text-text-muted sm:block">
              ESC
            </kbd>
          </div>

          <div ref={listRef} className="scroll-thin max-h-[52vh] overflow-y-auto p-1.5">
            {visible.length === 0 ? (
              <p className="px-2 py-6 text-center text-caption text-text-muted">
                Nothing matches “{query}”.
              </p>
            ) : (
              Object.entries(grouped).map(([group, items]) => (
                <div key={group} className="mb-1 last:mb-0">
                  <p className="px-2 py-1 text-micro font-semibold uppercase tracking-[0.09em] text-text-muted">
                    {group}
                  </p>
                  {items.map((command) => {
                    flatIndex += 1;
                    const index = flatIndex;
                    const Icon = command.icon;

                    return (
                      <button
                        key={command.id}
                        type="button"
                        onMouseEnter={() => setCursor(index)}
                        onClick={() => runAt(index)}
                        className={cn(
                          "flex w-full items-center gap-2.5 rounded-chip px-2 py-2 text-left",
                          "text-meta transition-colors duration-fast",
                          index === cursor
                            ? "bg-accent-soft text-text-primary"
                            : "text-text-secondary hover:bg-surface-muted",
                        )}
                      >
                        <Icon className="h-3.5 w-3.5 shrink-0 text-text-muted" aria-hidden />
                        <span className="min-w-0 flex-1 truncate">{command.label}</span>
                        {command.hint ? (
                          <kbd className="shrink-0 rounded-chip border border-border px-1.5 py-0.5 text-micro text-text-muted">
                            {command.hint}
                          </kbd>
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              ))
            )}
          </div>

          <div className="flex items-center gap-3 border-t border-border px-3 py-2 text-micro text-text-muted">
            <span>↑↓ navigate</span>
            <span>↵ run</span>
            <span className="ml-auto">⌘K anywhere</span>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
