"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useRef, type ReactNode } from "react";

import { confirm } from "@/stores/confirm-store";
import { cn } from "@/lib/utils";

export type ModalSize = "sm" | "md" | "lg" | "xl";

const SIZES: Record<ModalSize, string> = {
  sm: "sm:max-w-[480px]",
  md: "sm:max-w-[600px]",
  lg: "sm:max-w-[680px]",

  xl: "sm:max-w-[900px]",
};

export function Modal({
  open,
  onClose,
  title,
  description,
  footer,
  children,
  size = "md",
  busy = false,
  busyHint = "This is still running. It will close when it finishes.",
  dirty = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  footer?: ReactNode;
  children: ReactNode;
  size?: ModalSize;
  /**
   * A request this dialog started has not come back yet.
   *
   * Escape, the backdrop and the close button all dismiss a dialog, and none
   * of them cancelled the upload, import or save underneath — the request
   * carried on, its result landed nowhere, and the form that was half filled
   * in was gone. A dialog that cannot answer for what it started should not
   * be dismissable by three separate accidents.
   */
  busy?: boolean;
  busyHint?: string;
  /**
   * There is typed input in here that closing would throw away.
   *
   * Escape and a click on the backdrop are one keystroke and one stray click,
   * and both used to discard a filled-in connector form without a word. This
   * asks first. It is deliberately not `busy`: nothing is in flight, so
   * leaving is allowed — it just should not happen by accident.
   */
  dirty?: boolean;
}) {
  // While the confirmation is up, every pointer event lands outside this
  // dialog, so without this each click on it would ask the same question again.
  const asking = useRef(false);

  async function requestClose() {
    if (busy || asking.current) return;
    if (!dirty) {
      onClose();
      return;
    }

    asking.current = true;
    try {
      const discard = await confirm({
        title: "Discard what you have entered?",
        message: "Nothing here has been saved yet. Closing this loses it.",
        confirmLabel: "Discard",
        cancelLabel: "Keep editing",
        tone: "danger",
      });
      if (discard) onClose();
    } finally {
      asking.current = false;
    }
  }

  const hold = (event: Event) => {
    if (busy || asking.current) {
      event.preventDefault();
      return;
    }
    if (dirty) {
      event.preventDefault();
      void requestClose();
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && void requestClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-overlay backdrop-blur-[1px]" />
        <Dialog.Content
          aria-busy={busy || undefined}
          onEscapeKeyDown={hold}
          onPointerDownOutside={hold}
          onInteractOutside={hold}
          className={cn(
            "fixed left-1/2 top-1/2 z-50 flex -translate-x-1/2 -translate-y-1/2 flex-col",
            "w-[calc(100vw-24px)] max-h-[calc(100dvh-24px)] sm:max-h-[86vh]",
            "rounded-card border border-border bg-surface shadow-popover focus:outline-none",
            SIZES[size],
          )}

          {...(description ? {} : { "aria-describedby": undefined })}
        >
          {busy ? (
            <span
              aria-hidden
              className="absolute inset-x-0 top-0 h-0.5 overflow-hidden rounded-t-card"
            >
              <span className="animate-modal-progress block h-full w-1/3 bg-accent" />
            </span>
          ) : null}

          <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3 sm:px-5 sm:py-3.5">
            <div className="min-w-0">
              <Dialog.Title className="text-title font-semibold text-text-primary">
                {title}
              </Dialog.Title>
              {description ? (
                <Dialog.Description className="mt-0.5 text-caption text-text-muted">
                  {description}
                </Dialog.Description>
              ) : null}
            </div>
            <button
              type="button"
              aria-label="Close"
              onClick={() => void requestClose()}
              disabled={busy}
              title={busy ? busyHint : undefined}
              className={cn(
                "-mr-1 shrink-0 rounded-input p-1.5 text-text-muted transition-colors duration-fast",
                "hover:bg-surface-muted hover:text-text-primary",
                "disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent",
              )}
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </div>

          <div className="scroll-thin flex-1 overflow-y-auto px-4 py-4 sm:px-5">{children}</div>

          {footer ? (
            <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border px-4 py-3 sm:px-5">
              {footer}
            </div>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
