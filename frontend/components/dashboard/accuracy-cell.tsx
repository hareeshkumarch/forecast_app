"use client";

import { formatPercent, humanizeModel } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ModelKind } from "@/types/api";

export function AccuracyCell({
  value,
  measured,
  model,
  mase,
  className,
}: {
  value: number | null;
  measured: boolean;
  model: ModelKind | null;

  mase?: number | null;
  className?: string;
}) {
  if (value === null) {
    if (mase == null) {
      return <span className={cn("text-text-muted", className)}>—</span>;
    }

    const beatsFree = mase < 1;
    return (
      <span
        className={cn("inline-flex items-center gap-1", className)}
        title={
          beatsFree
            ? `Too little demand to quote an accuracy. Against simply repeating last season it was ${(1 - mase) * 100 > 0 ? `${((1 - mase) * 100).toFixed(0)}% better` : "no better"}.`
            : "Too little demand to quote an accuracy, and it did no better than simply repeating last season."
        }
      >
        <span className={cn("num", beatsFree ? "text-text-secondary" : "text-warning")}>
          {mase.toFixed(2)}×
        </span>
        <span
          aria-label="Compared with repeating last season"
          className="rounded-[3px] border border-border px-1 text-[9px] font-medium uppercase leading-[13px] tracking-[0.04em] text-text-muted"
        >
          vs naive
        </span>
      </span>
    );
  }

  const title = measured
    ? `Backtested on this segment${model ? ` with ${humanizeModel(model)}` : ""}`
    : "Not enough history to backtest this segment — the overall accuracy is shown instead";

  return (
    <span className={cn("inline-flex items-center gap-1", className)} title={title}>
      <span className={cn("num", measured ? "text-text-secondary" : "text-text-muted")}>
        {formatPercent(value)}
      </span>
      {measured ? null : (
        <span
          aria-label="Estimated"
          className="rounded-[3px] border border-border px-1 text-[9px] font-medium uppercase leading-[13px] tracking-[0.04em] text-text-muted"
        >
          est
        </span>
      )}
    </span>
  );
}
