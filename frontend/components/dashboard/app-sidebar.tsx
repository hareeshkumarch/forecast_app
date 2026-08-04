"use client";

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

import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";

export const APP_NAV: { href: string; label: string; description: string; icon: LucideIcon }[] = [
  { href: "/", label: "Dashboard", description: "Forecast overview", icon: LayoutDashboard },
  { href: "/reports", label: "Reports", description: "Runs and exports", icon: FileBarChart2 },
  { href: "/connectors", label: "Connectors", description: "Data sources", icon: Database },
  { href: "/usage", label: "LLM Usage", description: "Tokens, cost and latency", icon: Activity },
  { href: "/settings", label: "Settings", description: "Appearance and providers", icon: Settings },
];

export type AppSection = "dashboard" | "reports" | "connectors" | "usage" | "settings";

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function AppSidebar() {
  return (
    <aside
      aria-label="Primary navigation"
      className="hidden w-[208px] shrink-0 flex-col border-r border-border bg-surface lg:flex"
    >
      <AppSidebarBody />
    </aside>
  );
}

export function AppSidebarBody() {
  const pathname = usePathname();
  const closeRail = useUiStore((state) => state.closeRail);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="px-4 pb-2 pt-4">
        <p className="eyebrow">Workspace</p>
      </div>
      <nav className="flex-1 space-y-1 px-2.5" aria-label="Application sections">
        {APP_NAV.map((item) => {
          const Icon = item.icon;
          const active = isActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={closeRail}
              aria-current={active ? "page" : undefined}
              className={cn(
                "group flex min-h-11 items-center gap-3 rounded-input border px-2.5 py-2 sm:min-h-10",
                "transition-colors duration-fast",
                active
                  ? "border-accent-border bg-accent-soft text-text-primary"
                  : "border-transparent text-text-secondary hover:bg-surface-muted hover:text-text-primary",
              )}
            >
              <span
                className={cn(
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px]",
                  active ? "bg-surface text-accent shadow-card" : "bg-surface-muted text-text-muted",
                )}
              >
                <Icon className="h-3.5 w-3.5" aria-hidden />
              </span>
              <span className="min-w-0">
                <span className="block truncate text-meta font-medium">{item.label}</span>
                <span className="block truncate text-caption text-text-muted">{item.description}</span>
              </span>
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-border p-3">
        <div className="rounded-card border border-border bg-surface-muted p-3">
          <p className="text-caption font-medium text-text-primary">Forecast workspace</p>
          <p className="mt-1 text-caption leading-[15px] text-text-muted">
            Models, data sources, reports, and AI operations in one place.
          </p>
        </div>
      </div>
    </div>
  );
}
