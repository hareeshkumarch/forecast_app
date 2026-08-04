"use client";

import * as Tooltip from "@radix-ui/react-tooltip";
import {
  Activity,
  Database,
  FileBarChart2,
  LayoutDashboard,
  Settings,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { cn } from "@/lib/utils";
import { usePrefsStore } from "@/stores/prefs-store";
import { useUiStore } from "@/stores/ui-store";

export const APP_NAV: { href: string; label: string; description: string; icon: LucideIcon }[] = [
  { href: "/", label: "Dashboard", description: "Forecast overview", icon: LayoutDashboard },
  { href: "/reports", label: "Reports", description: "Runs and exports", icon: FileBarChart2 },
  { href: "/connectors", label: "Connectors", description: "Data sources", icon: Database },
  { href: "/usage", label: "LLM Usage", description: "Tokens and cost", icon: Activity },
  { href: "/settings", label: "Settings", description: "Theme and providers", icon: Settings },
];

export type AppSection = "dashboard" | "reports" | "connectors" | "usage" | "settings";

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

/**
 * `[` toggles the rail. Ignored while typing, so it never eats a bracket in a
 * dataset name or a query.
 */
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
  useSidebarShortcut();

  return (
    <Tooltip.Provider delayDuration={250} skipDelayDuration={80}>
      <aside
        id="app-navigation"
        aria-label="Primary navigation"
        data-collapsed={collapsed ? "" : undefined}
        className={cn(
          "hidden shrink-0 flex-col border-r border-border bg-surface lg:flex",
          "transition-[width] duration-200 ease-out motion-reduce:transition-none",
          collapsed ? "w-[60px]" : "w-[212px]",
        )}
      >
        <AppSidebarBody collapsed={collapsed} />
      </aside>
    </Tooltip.Provider>
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
      className={cn(
        "group relative flex min-h-11 items-center rounded-input border transition-colors duration-fast sm:min-h-10",
        collapsed ? "justify-center px-0" : "gap-2.5 px-2 py-1.5",
        active
          ? "border-accent-border bg-accent-soft text-text-primary"
          : "border-transparent text-text-secondary hover:bg-surface-muted hover:text-text-primary",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r-full bg-accent transition-opacity duration-fast",
          active ? "opacity-100" : "opacity-0",
        )}
      />
      <span
        className={cn(
          "flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px] transition-colors duration-fast",
          active
            ? "bg-surface text-accent shadow-card"
            : "bg-surface-muted text-text-muted group-hover:text-text-secondary",
        )}
      >
        <Icon className="h-3.5 w-3.5" aria-hidden />
      </span>
      {collapsed ? (
        <span className="sr-only">{item.label}</span>
      ) : (
        <span className="min-w-0 flex-1">
          <span className="block truncate text-meta font-medium leading-tight">{item.label}</span>
          <span className="block truncate text-caption leading-tight text-text-muted">
            {item.description}
          </span>
        </span>
      )}
    </Link>
  );

  if (!collapsed) return link;

  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{link}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side="right"
          sideOffset={8}
          className="z-50 rounded-card border border-border bg-surface px-2 py-1.5 shadow-popover"
        >
          <p className="text-meta font-medium text-text-primary">{item.label}</p>
          <p className="text-caption text-text-muted">{item.description}</p>
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

export function AppSidebarBody({ collapsed = false }: { collapsed?: boolean }) {
  const pathname = usePathname();
  const closeRail = useUiStore((state) => state.closeRail);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {collapsed ? (
        <div className="h-3" />
      ) : (
        <div className="px-3 pb-2 pt-4">
          <p className="eyebrow">Workspace</p>
        </div>
      )}

      <nav
        className={cn("flex-1 space-y-1 overflow-y-auto pb-3", collapsed ? "px-2" : "px-2.5")}
        aria-label="Application sections"
      >
        {APP_NAV.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            active={isActive(pathname, item.href)}
            collapsed={collapsed}
            onNavigate={closeRail}
          />
        ))}
      </nav>

    </div>
  );
}
