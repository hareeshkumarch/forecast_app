"use client";

import { formatPercent, humanizeModel } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ModelKind } from "@/types/api";

/**
 * A segment's accuracy, marked according to where the number came from.
 *
 * A measured figure is the segment's own backtest. An estimated one is the top
 * line's accuracy standing in, because the segment had too little history to
 * validate a model of its own — worth showing, but not worth showing as though
 * it were the same kind of number.
 */
export function AccuracyCell({
  value,
  measured,
  model,
  className,
}: {
  value: number | null;
  measured: boolean;
  model: ModelKind | null;
  className?: string;
}) {
  if (value === null) {
    return <span className={cn("text-text-muted", className)}>—</span>;
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
