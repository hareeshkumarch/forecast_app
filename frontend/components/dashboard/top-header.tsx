"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  BookOpen,
  Menu,
  Monitor,
  MoreVertical,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Sparkles,
  Sun,
  TrendingUp,
} from "lucide-react";
import Link from "next/link";

import type { AppSection } from "@/components/dashboard/app-sidebar";
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
import { RAIL_MEDIA, useMediaQuery } from "@/hooks/use-media-query";
import { API_BASE_URL } from "@/lib/api";
import { cn } from "@/lib/utils";
import { usePrefsStore } from "@/stores/prefs-store";
import { useUiStore } from "@/stores/ui-store";

const DOCS_URL = `${API_BASE_URL}/docs`;

const SECTION_LABEL: Record<AppSection, string> = {
  dashboard: "Dashboard",
  reports: "Reports",
  connectors: "Connectors",
  usage: "LLM Usage",
  settings: "Settings",
};

export function TopHeader({ section }: { section: AppSection }) {
  const openRail = useUiStore((state) => state.openRail);
  const { data: insights } = useInsights();
  const theme = usePrefsStore((state) => state.theme);
  const resolvedTheme = usePrefsStore((state) => state.resolvedTheme);
  const toggleTheme = usePrefsStore((state) => state.toggleTheme);
  const sidebarCollapsed = usePrefsStore((state) => state.sidebarCollapsed);
  const toggleSidebar = usePrefsStore((state) => state.toggleSidebar);
  const isDesktop = useMediaQuery(RAIL_MEDIA.navigation);

  const isDashboard = section === "dashboard";
  const insightCount = insights?.items.length ?? 0;
  const ThemeIcon = theme === "system" ? Monitor : resolvedTheme === "dark" ? Moon : Sun;

  // Below `lg` the sidebar is a sheet, so the same control opens it there.
  const toggleNavigation = isDesktop ? toggleSidebar : () => openRail("navigation");
  const navigationLabel = !isDesktop
    ? "Open navigation"
    : sidebarCollapsed
      ? "Expand navigation"
      : "Collapse navigation";
  const NavIcon = !isDesktop ? Menu : sidebarCollapsed ? PanelLeftOpen : PanelLeftClose;

  return (
    <header className="flex h-header shrink-0 items-center gap-2 border-b border-border bg-surface px-2 sm:gap-2.5 sm:px-5">
      <button
        type="button"
        onClick={toggleNavigation}
        aria-label={navigationLabel}
        title={navigationLabel}
        aria-expanded={isDesktop ? !sidebarCollapsed : false}
        aria-controls="app-navigation"
        className={cn(
          "group flex min-h-11 items-center gap-2.5 rounded-input px-1 -mx-1",
          "transition-colors duration-fast hover:bg-surface-muted sm:min-h-0 sm:py-1",
        )}
      >
        <span
          className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] bg-accent"
          aria-hidden
        >
          <TrendingUp className="h-4 w-4 text-white transition-opacity duration-fast group-hover:opacity-0" />
          <NavIcon className="absolute h-4 w-4 text-white opacity-0 transition-opacity duration-fast group-hover:opacity-100" />
        </span>
        <span className="hidden truncate text-subhead font-semibold tracking-[-0.01em] text-text-primary sm:block sm:text-title">
          Forecast Hub
        </span>
      </button>

      <span className="hidden h-5 w-px bg-border sm:block" aria-hidden />
      <span className="hidden truncate text-meta font-medium text-text-secondary sm:block">
        {SECTION_LABEL[section]}
      </span>

      <div className="ml-auto flex items-center gap-1 sm:gap-2">
        {isDashboard ? (
          <>
            <div className="hidden items-center gap-2 md:flex">
              <RunControl />
              <ScenarioControl />
              <RangeControl />
            </div>
            <div className="md:hidden">
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
            className={cn(ICON_BUTTON, "relative min-[1720px]:hidden")}
          >
            <Sparkles className="h-4 w-4 text-accent" aria-hidden />
            {insightCount > 0 ? (
              <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[9px] font-semibold leading-none text-white num">
                {insightCount > 9 ? "9+" : insightCount}
              </span>
            ) : null}
          </button>
        ) : null}
      </div>
    </header>
  );
}
