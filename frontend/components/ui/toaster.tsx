"use client";

import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { useToastStore, type ToastTone } from "@/stores/toast-store";

const TONES: Record<ToastTone, { icon: typeof Info; ring: string; text: string }> = {
  success: { icon: CheckCircle2, ring: "border-positive-border", text: "text-positive" },
  error: { icon: AlertTriangle, ring: "border-negative-border", text: "text-negative" },
  info: { icon: Info, ring: "border-border", text: "text-text-secondary" },
};

/**
 * Bottom-left on desktop, full width above the fold on phones. Polite rather
 * than assertive: these confirm what just happened, they do not interrupt.
 */
export function Toaster() {
  const toasts = useToastStore((state) => state.toasts);
  const dismiss = useToastStore((state) => state.dismiss);

  if (toasts.length === 0) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none fixed bottom-3 left-3 right-3 z-[60] flex flex-col gap-2 sm:right-auto sm:w-[340px]"
    >
      {toasts.map((item) => {
        const tone = TONES[item.tone];
        const Icon = tone.icon;

        return (
          <div
            key={item.id}
            className={cn(
              "pointer-events-auto flex items-start gap-2.5 rounded-card border bg-surface p-3 shadow-popover",
              "animate-toast-in",
              tone.ring,
            )}
          >
            <Icon className={cn("mt-px h-4 w-4 shrink-0", tone.text)} aria-hidden />

            <div className="min-w-0 flex-1">
              <p className="text-body font-medium text-text-primary">{item.title}</p>
              {item.description ? (
                <p className="mt-0.5 text-caption leading-[16px] text-text-secondary">
                  {item.description}
                </p>
              ) : null}
              {item.action ? (
                <button
                  type="button"
                  onClick={() => {
                    item.action?.onClick();
                    dismiss(item.id);
                  }}
                  className="mt-1.5 text-caption font-medium text-accent transition-colors duration-fast hover:text-accent-hover"
                >
                  {item.action.label}
                </button>
              ) : null}
            </div>

            <button
              type="button"
              aria-label="Dismiss"
              onClick={() => dismiss(item.id)}
              className="-mr-1 -mt-1 shrink-0 rounded-input p-1 text-text-muted transition-colors duration-fast hover:bg-surface-muted hover:text-text-primary"
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
        );
      })}
    </div>
  );
}
