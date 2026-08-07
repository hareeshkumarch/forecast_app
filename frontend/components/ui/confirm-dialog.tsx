"use client";

import { AlertTriangle, HelpCircle } from "lucide-react";

import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/primitives";
import { useConfirmStore } from "@/stores/confirm-store";

export function ConfirmDialog() {
  const request = useConfirmStore((state) => state.request);
  const resolve = useConfirmStore((state) => state.resolve);

  const danger = request?.tone !== "default";
  const Icon = danger ? AlertTriangle : HelpCircle;

  return (
    <Modal
      open={Boolean(request)}
      onClose={() => resolve(false)}
      title={request?.title ?? ""}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={() => resolve(false)}>
            {request?.cancelLabel ?? "Keep it"}
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={() => resolve(true)} autoFocus>
            {request?.confirmLabel ?? "Confirm"}
          </Button>
        </>
      }
    >
      <div className="flex items-start gap-3">
        <span
          className={
            danger
              ? "flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-negative-border bg-negative-soft"
              : "flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-border bg-surface-muted"
          }
        >
          <Icon
            className={danger ? "h-4 w-4 text-negative" : "h-4 w-4 text-text-muted"}
            aria-hidden
          />
        </span>
        <p className="min-w-0 text-meta text-text-secondary">{request?.message}</p>
      </div>
    </Modal>
  );
}
