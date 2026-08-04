"use client";


import * as Dialog from "@radix-ui/react-dialog";
import * as VisuallyHidden from "@radix-ui/react-visually-hidden";
import { X } from "lucide-react";
import { useEffect } from "react";

import { AppSidebarBody } from "@/components/dashboard/app-sidebar";
import { InsightsRailBody } from "@/components/insights/insights-rail";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";

/** Mirrors the `lg` / `2xl` breakpoints the two rails become visible at. */
const RAIL_MEDIA = {
  navigation: "(min-width: 1024px)",
  insights: "(min-width: 1720px)",
} as const;

/**
 * Serves either rail as an off-canvas sheet on viewports too narrow to show
 * it inline. Widening the window past the rail's own breakpoint dismisses the
 * sheet, so the content is never on screen twice.
 */
export function RailDrawer() {
  const rail = useUiStore((state) => state.mobileRail);
  const closeRail = useUiStore((state) => state.closeRail);

  useEffect(() => {
    if (!rail) return;

    const query = window.matchMedia(RAIL_MEDIA[rail]);
    if (query.matches) {
      closeRail();
      return;
    }

    const onChange = (event: MediaQueryListEvent) => {
      if (event.matches) closeRail();
    };
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [rail, closeRail]);

  const isNavigation = rail === "navigation";

  return (
    <Dialog.Root open={rail !== null} onOpenChange={(open) => !open && closeRail()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-overlay backdrop-blur-[1px]" />
        <Dialog.Content
          className={cn(
            "fixed inset-y-0 z-50 flex w-[86vw] max-w-[320px] flex-col bg-surface shadow-popover focus:outline-none",
            isNavigation ? "left-0 border-r border-border" : "right-0 border-l border-border",
          )}
          aria-describedby={undefined}
        >
          <VisuallyHidden.Root>
            <Dialog.Title>{isNavigation ? "Navigation" : "Forecast insights"}</Dialog.Title>
          </VisuallyHidden.Root>

          <Dialog.Close asChild>
            <button
              type="button"
              aria-label="Close"
              className="absolute right-2 top-2 z-10 flex h-11 w-11 items-center justify-center rounded-input text-text-muted transition-colors duration-fast hover:bg-surface-muted hover:text-text-primary sm:h-8 sm:w-8"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </Dialog.Close>

          {isNavigation ? <AppSidebarBody /> : <InsightsRailBody />}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
