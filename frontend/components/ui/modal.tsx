"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Widths are ceilings, not fixed sizes: every dialog shrinks to the viewport
 * with a gutter, so nothing overflows on a phone.
 */
export type ModalSize = "sm" | "md" | "lg";

const SIZES: Record<ModalSize, string> = {
  sm: "sm:max-w-[480px]",
  md: "sm:max-w-[600px]",
  lg: "sm:max-w-[680px]",
};

export function Modal({
  open,
  onClose,
  title,
  description,
  footer,
  children,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  footer?: ReactNode;
  children: ReactNode;
  size?: ModalSize;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-[#18202f]/25 backdrop-blur-[1px]" />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 flex -translate-x-1/2 -translate-y-1/2 flex-col",
            "w-[calc(100vw-24px)] max-h-[calc(100dvh-24px)] sm:max-h-[86vh]",
            "rounded-card border border-border bg-surface shadow-popover focus:outline-none",
            SIZES[size],
          )}
          // Radix warns when a dialog renders no <Dialog.Description>. Clearing
          // the attribute silences it — but only when there is nothing to point
          // at, otherwise it would undo Radix's own association.
          {...(description ? {} : { "aria-describedby": undefined })}
        >
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
            <Dialog.Close asChild>
              <button
                type="button"
                aria-label="Close"
                className="-mr-1 shrink-0 rounded-input p-1.5 text-text-muted transition-colors duration-fast hover:bg-surface-muted hover:text-text-primary"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </Dialog.Close>
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
