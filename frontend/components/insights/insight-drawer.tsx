"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";

import { Badge } from "@/components/ui/primitives";
import { formatMetric, humanizeKey } from "@/lib/format";
import { useUiStore } from "@/stores/ui-store";
import type { InsightSeverity } from "@/types/api";

const SEVERITY_TONE: Record<InsightSeverity, "positive" | "neutral" | "warning" | "negative"> = {
  positive: "positive",
  info: "neutral",
  warning: "warning",
  critical: "negative",
};

const SEVERITY_LABEL: Record<InsightSeverity, string> = {
  positive: "Positive",
  info: "Informational",
  warning: "Warning",
  critical: "Critical",
};

function formatSupportingValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? value.toLocaleString("en-US") : value.toFixed(2);
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

export function InsightDrawer() {
  const insight = useUiStore((state) => state.insightDrawer);
  const closeInsight = useUiStore((state) => state.closeInsight);

  return (
    <Dialog.Root open={Boolean(insight)} onOpenChange={(open) => !open && closeInsight()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-overlay" />
        <Dialog.Content
          className="fixed right-0 top-0 z-50 flex h-full w-[420px] flex-col border-l border-border bg-surface shadow-popover focus:outline-none"
          aria-describedby={undefined}
        >
          {insight ? (
            <>
              <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Badge tone={SEVERITY_TONE[insight.severity]}>
                      {SEVERITY_LABEL[insight.severity]}
                    </Badge>
                    <span className="text-caption text-text-muted">
                      {insight.type.replace(/_/g, " ")}
                    </span>
                  </div>
                  <Dialog.Title className="mt-2 text-title font-semibold text-text-primary">
                    {insight.title}
                  </Dialog.Title>
                </div>
                <Dialog.Close asChild>
                  <button
                    type="button"
                    aria-label="Close"
                    className="rounded-input p-1.5 text-text-muted transition-colors duration-fast hover:bg-surface-muted hover:text-text-primary"
                  >
                    <X className="h-4 w-4" aria-hidden />
                  </button>
                </Dialog.Close>
              </div>

              <div className="scroll-thin flex-1 space-y-5 overflow-y-auto px-5 py-4">
                <section>
                  <h3 className="eyebrow">What we found</h3>
                  <p className="mt-1.5 text-body text-text-secondary">
                    {insight.explanation}
                  </p>
                </section>

                <section>
                  <h3 className="eyebrow">Suggested action</h3>
                  <p className="mt-1.5 rounded-card border border-accent-border bg-accent-soft px-3 py-2.5 text-body text-text-primary">
                    {insight.suggested_action}
                  </p>
                </section>

                <section>
                  <h3 className="eyebrow">Supporting metric</h3>
                  <div className="mt-1.5 rounded-card border border-border bg-surface-muted px-3 py-2.5">
                    <p className="text-caption text-text-muted">
                      {humanizeKey(insight.metric_name)}
                    </p>
                    <p className="mt-0.5 text-heading font-semibold text-text-primary num">
                      {formatMetric(insight.metric_value, insight.metric_unit)}
                    </p>
                  </div>
                </section>

                {Object.keys(insight.supporting_data).length > 0 ? (
                  <section>
                    <h3 className="eyebrow">Supporting data</h3>
                    <dl className="mt-1.5 divide-y divide-border rounded-card border border-border">
                      {Object.entries(insight.supporting_data).map(([key, value]) => (
                        <div key={key} className="flex items-center justify-between gap-3 px-3 py-2">
                          <dt className="text-caption text-text-secondary">{humanizeKey(key)}</dt>
                          <dd className="text-meta font-medium text-text-primary num">
                            {formatSupportingValue(value)}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </section>
                ) : null}

                <p className="text-caption text-text-muted">
                  Generated {new Date(insight.generated_at).toLocaleString()}
                  {insight.llm_rewritten
                    ? " · wording refined by an LLM; all figures are computed"
                    : " · computed from forecast output"}
                </p>
              </div>
            </>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
