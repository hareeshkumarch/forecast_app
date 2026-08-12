"use client";

import { Maximize2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Modal } from "@/components/ui/modal";
import {
  Card,
  EmptyState,
  ErrorState,
  IconButton,
  PanelHeader,
  Skeleton,
} from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

export function Panel({
  title,
  subtitle,

  state,

  isEmpty = false,
  empty,

  enlarged,
  actions,
  skeleton,
  className,
  children,
}: {
  title: string;
  subtitle?: string;
  state: { isLoading: boolean; isError: boolean; error?: unknown; refetch: () => void };
  isEmpty?: boolean;
  empty?: { title: string; message?: string; icon?: Parameters<typeof EmptyState>[0]["icon"] };
  enlarged?: { title: string; description?: string; content: ReactNode };
  actions?: ReactNode;
  skeleton?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <Card className={cn("flex min-w-0 flex-col", className)}>
        <PanelHeader
          title={title}
          subtitle={subtitle}
          actions={
            <div className="flex items-center gap-0.5">
              {actions}
              {enlarged ? (
                <IconButton
                  label={`Enlarge ${title.toLowerCase()}`}
                  icon={Maximize2}
                  onClick={() => setOpen(true)}

                  disabled={state.isLoading || state.isError || isEmpty}
                />
              ) : null}
            </div>
          }
        />

        <div className="min-h-0 flex-1 px-3 pb-3">
          {state.isLoading ? (
            (skeleton ?? <DefaultSkeleton />)
          ) : state.isError ? (
            <ErrorState error={state.error} onRetry={state.refetch} />
          ) : isEmpty ? (
            <EmptyState
              className="chart-box"
              icon={empty?.icon}
              title={empty?.title ?? "Nothing to show yet"}
              message={empty?.message}
            />
          ) : (
            children
          )}
        </div>
      </Card>

      {enlarged ? (
        <Modal
          open={open}
          onClose={() => setOpen(false)}
          title={enlarged.title}
          description={enlarged.description}
          size="xl"
        >
          {enlarged.content}
        </Modal>
      ) : null}
    </>
  );
}

function DefaultSkeleton() {
  return (
    <div className="space-y-2 px-1 pt-2" aria-hidden>
      <Skeleton className="h-3 w-40" />
      <Skeleton className="chart-box w-full " />
    </div>
  );
}
