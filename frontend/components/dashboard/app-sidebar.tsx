"use client";

import * as Tooltip from "@radix-ui/react-tooltip";
import {
  Activity,
  Database,
  FileBarChart2,
  LayoutDashboard,
  Layers,
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
  { href: "/series", label: "Series", description: "Triage by value at risk", icon: Layers },
  { href: "/reports", label: "Reports", description: "Runs and exports", icon: FileBarChart2 },
  { href: "/connectors", label: "Connectors", description: "Data sources", icon: Database },
  { href: "/usage", label: "LLM Usage", description: "Tokens and cost", icon: Activity },
  { href: "/settings", label: "Settings", description: "Theme and providers", icon: Settings },
];

export type AppSection =
  | "dashboard"
  | "series"
  | "reports"
  | "connectors"
  | "usage"
  | "settings";

/**
 * The rail's two widths.
 *
 * They are not arbitrary: the nav's padding (12px) plus an item's own (10px)
 * puts every icon 22px from the rail's edge, so a collapsed rail of
 * 22 + 16 + 22 leaves each icon exactly where the expanded rail had it. The
 * rail narrows around the icons rather than moving them.
 */
const RAIL_WIDTH = { expanded: "w-rail", collapsed: "w-[60px]" } as const;

/**
 * How a label behaves while the rail changes width.
 *
 * Text is the first thing to go and the last to arrive. Closing, it fades out
 * ahead of the width so it is never seen being squeezed; opening, it waits for
 * the rail to make room rather than spilling out of a 60px column and being
 * clipped. The rail animates over 200ms, so the two halves sit either side of
 * that.
 */
const LABEL_FADE = {
  hidden: "opacity-0 duration-100",
  shown: "opacity-100 delay-150 duration-150",
} as const;

function labelFade(collapsed: boolean): string {
  return cn(
    "transition-opacity ease-out motion-reduce:transition-none motion-reduce:delay-0",
    collapsed ? LABEL_FADE.hidden : LABEL_FADE.shown,
  );
}

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
    <aside
      id="app-navigation"
      aria-label="Primary navigation"
      data-collapsed={collapsed ? "" : undefined}
      className={cn(
        "hidden shrink-0 flex-col overflow-hidden border-r border-border bg-surface lg:flex",
        "transition-[width] duration-200 ease-out motion-reduce:transition-none",
        collapsed ? RAIL_WIDTH.collapsed : RAIL_WIDTH.expanded,
      )}
    >
      <AppSidebarBody collapsed={collapsed} />
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
      {/* Positioned out of flow so a collapsed item is exactly an icon wide,
          and so the link keeps its accessible name in both states. */}
      <span
        className={cn(
          "absolute left-[34px] right-2.5 truncate text-meta font-medium leading-none",
          labelFade(collapsed),
        )}
      >
        {item.label}
      </span>
    </Link>
  );

  // The tinted pill and the accent icon already say which section you are in,
  // in both widths. An edge marker on top of them would be a third signal —
  // and the rail sits flush against the window, so it read as a clipped sliver
  // rather than an indicator.
  //
  // The trigger stays mounted whether or not there is a tooltip to show:
  // swapping the link between a wrapped and an unwrapped branch remounts it,
  // and a freshly mounted element has no previous opacity to animate from — so
  // the label popped in at full strength while the rail was still 60px wide.
  return (
    <li>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>{link}</Tooltip.Trigger>
        {collapsed ? (
          <Tooltip.Portal>
            <Tooltip.Content
              side="right"
              // An item ends 12px inside the rail, so anything less than that
              // opens the tooltip on top of the rail's own border.
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

export function AppSidebarBody({ collapsed = false }: { collapsed?: boolean }) {
  const pathname = usePathname();
  const closeRail = useUiStore((state) => state.closeRail);

  return (
    <div className="flex min-h-0 flex-1 flex-col pb-3">
      {/* Fixed height in both states: the label goes, the rhythm stays, and
          nothing below it shifts as the rail narrows. */}
      <div className="flex h-11 shrink-0 items-end px-3 pb-1.5">
        <p className={cn("eyebrow truncate", labelFade(collapsed))}>Workspace</p>
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
