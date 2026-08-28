"use client";

import * as Tooltip from "@radix-ui/react-tooltip";
import {
  Activity,
  ChevronRight,
  Database,
  FileBarChart2,
  FileSpreadsheet,
  FlaskConical,
  LayoutDashboard,
  Layers,
  Settings,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { cn } from "@/lib/utils";
import { usePrefsStore } from "@/stores/prefs-store";
import { useUiStore } from "@/stores/ui-store";

const APP_NAV: { href: string; label: string; description: string; icon: LucideIcon }[] = [
  { href: "/dashboard", label: "Dashboard", description: "Forecast overview", icon: LayoutDashboard },
  { href: "/series", label: "Series", description: "Triage by value at risk", icon: Layers },
  { href: "/datasets", label: "Data", description: "Files you have uploaded", icon: FileSpreadsheet },
  { href: "/reports", label: "Reports", description: "Runs and exports", icon: FileBarChart2 },
  { href: "/scenarios", label: "Scenarios", description: "What-if, compare and monitor", icon: FlaskConical },
  { href: "/connectors", label: "Connectors", description: "Data sources", icon: Database },
  { href: "/usage", label: "LLM Usage", description: "Tokens and cost", icon: Activity },
  { href: "/account", label: "Account", description: "You, and who else may sign in", icon: UserRound },
  { href: "/settings", label: "Settings", description: "Theme and providers", icon: Settings },
];

export type AppSection =
  | "dashboard"
  | "series"
  | "datasets"
  | "reports"
  | "scenarios"
  | "connectors"
  | "usage"
  | "account"
  | "settings";

const RAIL_WIDTH = { expanded: "w-rail", collapsed: "w-[60px]" } as const;

const LABEL_FADE = {
  hidden: "opacity-0 duration-100",
  shown: "opacity-100 delay-150 duration-150",
} as const;

function labelFade(collapsed: boolean): string {
  return cn(
    "transition-opacity ease-out motion-reduce:transition-none motion-reduce:delay-0",
    // Faded out is not gone: without this the labels stay clickable and
    // selectable inside a rail that reads as icon-only.
    collapsed ? cn(LABEL_FADE.hidden, "pointer-events-none select-none") : LABEL_FADE.shown,
  );
}

function isActive(pathname: string, href: string): boolean {
  // `/dashboard` is the app root and has no children, so it matches exactly.
  // Everything else owns its subtree.
  return href === "/dashboard" ? pathname === "/dashboard" : pathname.startsWith(href);
}

function useSidebarShortcut(): void {
  const toggleSidebar = usePrefsStore((state) => state.toggleSidebar);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "[" || event.metaKey || event.ctrlKey || event.altKey) return;

      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return;

      event.preventDefault();
      toggleSidebar();
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [toggleSidebar]);
}

export function AppSidebar() {
  const collapsed = usePrefsStore((state) => state.sidebarCollapsed);
  const toggleSidebar = usePrefsStore((state) => state.toggleSidebar);
  useSidebarShortcut();

  return (
    <aside
      id="app-navigation"
      aria-label="Primary navigation"
      data-collapsed={collapsed ? "" : undefined}
      className={cn(
        "hidden shrink-0 flex-col overflow-hidden border-r border-border bg-surface/95 backdrop-blur-xl lg:flex",
        "transition-[width] duration-200 ease-out motion-reduce:transition-none",
        collapsed ? RAIL_WIDTH.collapsed : RAIL_WIDTH.expanded,
      )}
    >
      <AppSidebarBody collapsed={collapsed} onToggle={toggleSidebar} />
    </aside>
  );
}

function NavLink({
  item,
  active,
  collapsed,
  onNavigate,
}: {
  item: (typeof APP_NAV)[number];
  active: boolean;
  collapsed: boolean;
  onNavigate: () => void;
}) {
  const Icon = item.icon;

  const link = (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      aria-label={item.label}
      className={cn(
        "group relative flex h-9 items-center rounded-input px-2.5",
        "transition-colors duration-fast",
        active
          ? "bg-accent-soft text-text-primary"
          : "text-text-secondary hover:bg-surface-muted hover:text-text-primary",
      )}
    >
      <Icon
        className={cn(
          "h-4 w-4 shrink-0 transition-colors duration-fast",
          active ? "text-accent" : "text-text-muted group-hover:text-text-secondary",
        )}
        aria-hidden
      />

      <span
        aria-hidden={collapsed || undefined}
        className={cn(
          "absolute left-[34px] right-2.5 truncate text-meta-tight font-medium",
          labelFade(collapsed),
        )}
      >
        {item.label}
      </span>
    </Link>
  );

  return (
    <li>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>{link}</Tooltip.Trigger>
        {collapsed ? (
          <Tooltip.Portal>
            <Tooltip.Content
              side="right"

              sideOffset={16}
              className="z-50 rounded-card border border-border bg-surface px-2.5 py-1.5 shadow-popover"
            >
              <p className="text-meta font-medium text-text-primary">{item.label}</p>
              <p className="text-caption text-text-muted">{item.description}</p>
            </Tooltip.Content>
          </Tooltip.Portal>
        ) : null}
      </Tooltip.Root>
    </li>
  );
}

export function AppSidebarBody({
  collapsed = false,
  onToggle,
}: {
  collapsed?: boolean;
  onToggle?: () => void;
}) {
  const pathname = usePathname();
  const closeRail = useUiStore((state) => state.closeRail);

  return (
    <div className="flex min-h-0 flex-1 flex-col pb-3">

      <div className="relative flex h-11 shrink-0 items-end px-3 pb-1.5">
        <p
          aria-hidden={collapsed || undefined}
          className={cn(
            "absolute bottom-1.5 left-3 right-10 truncate",
            "eyebrow",
            labelFade(collapsed),
          )}
        >
          Workspace
        </p>

        {onToggle ? (
          <button
            type="button"
            onClick={onToggle}
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
            aria-expanded={!collapsed}
            aria-controls="app-navigation"
            className={cn(
              "flex h-7 w-7 shrink-0 items-center justify-center text-text-muted",
              "transition-colors duration-fast hover:bg-surface-muted hover:text-text-primary",
              collapsed ? "mx-auto" : "ml-auto",
            )}
          >
            <ChevronRight
              className={cn(
                "h-4 w-4 transition-transform duration-200 ease-out",
                "motion-reduce:transition-none",
                collapsed ? "" : "rotate-180",
              )}
              aria-hidden
            />
          </button>
        ) : null}
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-3" aria-label="Application sections">
        <ul className="space-y-0.5">
          {APP_NAV.map((item) => (
            <NavLink
              key={item.href}
              item={item}
              active={isActive(pathname, item.href)}
              collapsed={collapsed}
              onNavigate={closeRail}
            />
          ))}
        </ul>
      </nav>
    </div>
  );
}
