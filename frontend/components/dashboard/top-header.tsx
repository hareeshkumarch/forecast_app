"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  ArrowLeft,
  BookOpen,
  Monitor,
  MoreVertical,
  Moon,
  Settings,
  Sparkles,
  Sun,
  PanelLeft,
} from "lucide-react";
import Link from "next/link";

import type { AppSection } from "@/components/dashboard/app-sidebar";
import { Mark } from "@/components/marketing/mark";
import {
  CompactFilters,
  ExportControl,
  RangeControl,
  ResetFiltersControl,
  RunControl,
  ScenarioControl,
  StatusControl,
} from "@/components/dashboard/header-controls";
import { ICON_BUTTON, IconButton, MENU_CONTENT, MENU_ITEM } from "@/components/ui/primitives";
import { useInsights, useSummary } from "@/hooks/use-dashboard";
import { API_BASE_URL } from "@/lib/api";
import { cn } from "@/lib/utils";
import { usePrefsStore } from "@/stores/prefs-store";
import { useUiStore } from "@/stores/ui-store";

const DOCS_URL = `${API_BASE_URL}/docs`;

const SECTION_LABEL: Record<AppSection, string> = {
  dashboard: "Dashboard",
  series: "Series",
  datasets: "Data",
  reports: "Reports",
  scenarios: "Scenarios",
  connectors: "Connectors",
  usage: "LLM Usage",
  settings: "Settings",
};

export function TopHeader({ section }: { section: AppSection }) {
  const openRail = useUiStore((state) => state.openRail);
  const { data: insights } = useInsights();
  const { data: summary } = useSummary();
  const theme = usePrefsStore((state) => state.theme);
  const resolvedTheme = usePrefsStore((state) => state.resolvedTheme);
  const toggleTheme = usePrefsStore((state) => state.toggleTheme);

  const isDashboard = section === "dashboard" && (summary?.has_data ?? false);
  const insightCount = insights?.items.length ?? 0;
  const ThemeIcon = theme === "system" ? Monitor : resolvedTheme === "dark" ? Moon : Sun;

  return (
    <header className="flex h-header shrink-0 items-center gap-2 border-b border-border bg-surface/95 px-2 backdrop-blur-xl sm:gap-2.5 sm:px-5">
      <button
        type="button"
        onClick={() => openRail("navigation")}
        aria-label="Open navigation"
        aria-controls="app-navigation"
        className={cn(
          "flex min-h-11 w-9 shrink-0 items-center justify-center lg:hidden",
          "transition-colors duration-fast hover:bg-surface-muted fine:min-h-0 fine:h-8",
        )}
      >
        <PanelLeft className="h-4 w-4 text-text-muted" aria-hidden />
      </button>

      <Link
        href="/"
        aria-label="Forecast Hub, back to the home page"
        className={cn(
          "group -ml-0.5 flex min-h-11 items-center gap-2.5 px-1",
          "fine:min-h-0 fine:py-1",
        )}
      >
        <Mark size={24} />
        <span className="hidden truncate text-subhead font-bold tracking-[-0.035em] text-text-primary sm:block sm:text-title">
          Forecast Hub
        </span>
      </Link>

      <span className="hidden h-5 w-px bg-border sm:block" aria-hidden />
      <span className="hidden truncate text-meta font-medium text-text-secondary sm:block">
        {SECTION_LABEL[section]}
      </span>

      <div className="ml-auto flex min-w-0 items-center gap-1 sm:gap-2">
        {isDashboard ? (
          <>

            <div className="hidden min-w-0 items-center gap-2 xl:flex">
              <RunControl />
              <ScenarioControl />
              <RangeControl />
              <ResetFiltersControl />
            </div>
            <div className="xl:hidden">
              <CompactFilters />
            </div>
            <span className="mx-0.5 hidden h-5 w-px bg-border sm:block" aria-hidden />
          </>
        ) : null}

        <div className="hidden sm:block">
          <StatusControl />
        </div>
        {isDashboard ? <ExportControl /> : null}

        <IconButton
          label={`Theme: ${theme}. Switch to ${resolvedTheme === "dark" ? "light" : "dark"}`}
          icon={ThemeIcon}
          onClick={toggleTheme}
          className="hidden sm:inline-flex"
        />

        <a
          href={DOCS_URL}
          target="_blank"
          rel="noreferrer"
          aria-label="API documentation"
          title="API documentation"
          className={cn(ICON_BUTTON, "hidden sm:inline-flex")}
        >
          <BookOpen className="h-4 w-4" aria-hidden />
        </a>

        <Link
          href="/settings"
          aria-label="Settings"
          title="Settings"
          className={cn(ICON_BUTTON, "hidden sm:inline-flex")}
        >
          <Settings className="h-4 w-4" aria-hidden />
        </Link>

        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button type="button" aria-label="More" className={cn(ICON_BUTTON, "sm:hidden")}>
              <MoreVertical className="h-4 w-4" aria-hidden />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content align="end" sideOffset={6} className={MENU_CONTENT}>
              <DropdownMenu.Item asChild className={MENU_ITEM}>
                <Link href="/">
                  <ArrowLeft className="h-3.5 w-3.5 text-text-muted" aria-hidden />
                  Landing page
                </Link>
              </DropdownMenu.Item>
              <DropdownMenu.Item onSelect={toggleTheme} className={MENU_ITEM}>
                <ThemeIcon className="h-3.5 w-3.5 text-text-muted" aria-hidden />
                {resolvedTheme === "dark" ? "Light theme" : "Dark theme"}
              </DropdownMenu.Item>
              <DropdownMenu.Item asChild className={MENU_ITEM}>
                <Link href="/settings">
                  <Settings className="h-3.5 w-3.5 text-text-muted" aria-hidden />
                  Settings
                </Link>
              </DropdownMenu.Item>
              <DropdownMenu.Item asChild className={MENU_ITEM}>
                <a href={DOCS_URL} target="_blank" rel="noreferrer">
                  <BookOpen className="h-3.5 w-3.5 text-text-muted" aria-hidden />
                  API documentation
                </a>
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>

        {isDashboard ? (
          <button
            type="button"
            aria-label={`Forecast insights${insightCount > 0 ? ` (${insightCount})` : ""}`}
            title="Forecast insights"
            onClick={() => openRail("insights")}
            className={cn(ICON_BUTTON, "relative min-[1440px]:hidden")}
          >
            <Sparkles className="h-4 w-4 text-accent" aria-hidden />
            {insightCount > 0 ? (
              <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-tag font-semibold text-on-accent num">
                {insightCount > 9 ? "9+" : insightCount}
              </span>
            ) : null}
          </button>
        ) : null}
      </div>
    </header>
  );
}
