"use client";

import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { useEffect } from "react";

import { cn } from "@/lib/utils";
import { useToastStore, type Toast, type ToastTone } from "@/stores/toast-store";

const TONES: Record<ToastTone, { icon: typeof Info; ring: string; text: string }> = {
  success: { icon: CheckCircle2, ring: "border-positive-border", text: "text-positive" },
  error: { icon: AlertTriangle, ring: "border-negative-border", text: "text-negative" },
  info: { icon: Info, ring: "border-border", text: "text-text-secondary" },
};

/**
 * The text of what is on screen, for a reader that cannot see it.
 *
 * A live region has to already exist in the document to announce what is put
 * into it — a region added *with* its content is usually announced by nothing.
 * So two of them sit here empty from first paint. The cards stay reachable —
 * their dismiss and action buttons have to be — but they are not themselves
 * inside a live region, so nothing is announced twice. Errors go to the
 * assertive region: an upload that failed is worth interrupting for, and a
 * confirmation is not.
 */
function Announcements({ toasts }: { toasts: Toast[] }) {
  const say = (item: Toast) =>
    [item.title, item.description].filter(Boolean).join(". ");

  return (
    <>
      <div role="status" aria-live="polite" className="sr-only">
        {toasts
          .filter((item) => item.tone !== "error")
          .map((item) => (
            <p key={item.id}>{say(item)}</p>
          ))}
      </div>
      <div role="alert" aria-live="assertive" className="sr-only">
        {toasts
          .filter((item) => item.tone === "error")
          .map((item) => (
            <p key={item.id}>{say(item)}</p>
          ))}
      </div>
    </>
  );
}

export function Toaster() {
  const toasts = useToastStore((state) => state.toasts);
  const dismiss = useToastStore((state) => state.dismiss);
  const hold = useToastStore((state) => state.hold);
  const release = useToastStore((state) => state.release);

  // A toast fired at a tab nobody is looking at is a toast nobody sees. A run
  // that finished while the user was in their mail client should still have
  // something to say when they come back.
  useEffect(() => {
    const onVisibility = () => (document.hidden ? hold() : release());
    document.addEventListener("visibilitychange", onVisibility);
    if (document.hidden) hold();
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      release();
    };
  }, [hold, release]);

  return (
    <>
      <Announcements toasts={toasts} />

      {toasts.length === 0 ? null : (
        <div
          onMouseEnter={hold}
          onMouseLeave={release}
          onFocusCapture={hold}
          onBlurCapture={release}
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
                  <p className="flex items-center gap-1.5 text-body font-medium text-text-primary">
                    <span className="min-w-0 truncate">{item.title}</span>
                    {item.repeats > 1 ? (
                      <span
                        className="shrink-0 rounded-full border border-border bg-surface-muted px-1.5 text-caption font-normal tabular-nums text-text-muted"
                        title={`This happened ${item.repeats} times`}
                      >
                        ×{item.repeats}
                      </span>
                    ) : null}
                  </p>
                  {item.description ? (
                    <p className="mt-0.5 text-caption text-text-secondary">
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
      )}
    </>
  );
}
