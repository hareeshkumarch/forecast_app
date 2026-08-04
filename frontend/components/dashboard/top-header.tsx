"use client";


import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  BookOpen,
  Monitor,
  MoreVertical,
  Moon,
  PanelLeft,
  Settings,
  Sparkles,
  Sun,
  TrendingUp,
} from "lucide-react";

import {
  CompactFilters,
  ExportControl,
  RangeControl,
  RunControl,
  ScenarioControl,
  StatusControl,
} from "@/components/dashboard/header-controls";
import { ICON_BUTTON, IconButton, MENU_CONTENT, MENU_ITEM } from "@/components/ui/primitives";
import { useInsights } from "@/hooks/use-dashboard";
import { API_BASE_URL } from "@/lib/api";
import { cn } from "@/lib/utils";
import { usePrefsStore } from "@/stores/prefs-store";
import { useUiStore } from "@/stores/ui-store";

const DOCS_URL = `${API_BASE_URL}/docs`;

export function TopHeader() {
  const openRail = useUiStore((state) => state.openRail);
  const openModal = useUiStore((state) => state.openModal);
  const { data: insights } = useInsights();
  const theme = usePrefsStore((state) => state.theme);
  const resolvedTheme = usePrefsStore((state) => state.resolvedTheme);
  const toggleTheme = usePrefsStore((state) => state.toggleTheme);

  const insightCount = insights?.items.length ?? 0;
  const ThemeIcon = theme === "system" ? Monitor : resolvedTheme === "dark" ? Moon : Sun;

  return (
    <header className="flex h-header shrink-0 items-center gap-2 border-b border-border bg-surface px-3 sm:gap-2.5 sm:px-5">
      {/* The rails are drawers below their breakpoints; these open them. */}
      <IconButton
        label="Data connectors"
        icon={PanelLeft}
        onClick={() => openRail("connectors")}
        className="lg:hidden"
      />

      <div className="flex min-w-0 items-center gap-2.5">
        <span
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] bg-accent"
          aria-hidden
        >
          <TrendingUp className="h-4 w-4 text-white" />
        </span>
        <h1 className="truncate text-subhead font-semibold tracking-[-0.01em] text-text-primary sm:text-title">
          Forecasting Dashboard
        </h1>
      </div>

      <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
        <div className="hidden items-center gap-2 md:flex">
          <RunControl />
          <ScenarioControl />
          <RangeControl />
        </div>

        <div className="md:hidden">
          <CompactFilters />
        </div>

        <span className="mx-0.5 hidden h-5 w-px bg-border sm:block" aria-hidden />

        <StatusControl />
        <ExportControl />

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

        <IconButton
          label="Settings"
          icon={Settings}
          onClick={() => openModal("settings")}
          className="hidden sm:inline-flex"
        />

        {/* Everything that did not fit, for the narrowest viewports. */}
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button type="button" aria-label="More" className={cn(ICON_BUTTON, "sm:hidden")}>
              <MoreVertical className="h-4 w-4" aria-hidden />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content align="end" sideOffset={6} className={MENU_CONTENT}>
              <DropdownMenu.Item onSelect={toggleTheme} className={MENU_ITEM}>
                <ThemeIcon className="h-3.5 w-3.5 text-text-muted" aria-hidden />
                {resolvedTheme === "dark" ? "Light theme" : "Dark theme"}
              </DropdownMenu.Item>
              <DropdownMenu.Item onSelect={() => openModal("settings")} className={MENU_ITEM}>
                <Settings className="h-3.5 w-3.5 text-text-muted" aria-hidden />
                Settings
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

        <button
          type="button"
          aria-label={`AI insights${insightCount > 0 ? ` (${insightCount})` : ""}`}
          title="AI insights"
          onClick={() => openRail("insights")}
          className={cn(ICON_BUTTON, "relative 2xl:hidden")}
        >
          <Sparkles className="h-4 w-4 text-accent" aria-hidden />
          {insightCount > 0 ? (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[9px] font-semibold leading-none text-white num">
              {insightCount > 9 ? "9+" : insightCount}
            </span>
          ) : null}
        </button>
      </div>
    </header>
  );
}
