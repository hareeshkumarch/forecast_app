"use client";

import { CircleCheck, CircleAlert, CircleSlash, type LucideIcon } from "lucide-react";

import { Badge, Card, ErrorState, PanelHeader, Skeleton } from "@/components/ui/primitives";
import { useDecision } from "@/hooks/use-dashboard";
import { cn } from "@/lib/utils";
import type { DecisionGrade } from "@/types/api";

const GRADE: Record<
  DecisionGrade,
  { label: string; tone: "positive" | "warning" | "negative"; icon: LucideIcon }
> = {
  plannable: { label: "Plannable", tone: "positive", icon: CircleCheck },
  directional: { label: "Directional", tone: "warning", icon: CircleAlert },
  indicative: { label: "Indicative", tone: "negative", icon: CircleSlash },
};

export function DecisionPanel({ className }: { className?: string } = {}) {
  const { data, isLoading, isError, error, refetch } = useDecision();

  if (isLoading) return <Skeleton className={cn("h-56 w-full rounded-card", className)} />;
  if (isError) {
    return (
      <Card className={className}>
        <ErrorState error={error} onRetry={() => void refetch()} />
      </Card>
    );
  }
  if (!data?.has_decision || !data.grade) return null;

  const grade = GRADE[data.grade];
  const GradeIcon = grade.icon;

  return (
    <Card className={cn("flex min-w-0 flex-col", className)}>
      <PanelHeader
        title="What to plan to"
        subtitle={data.meaning ?? undefined}
        actions={
          <Badge tone={grade.tone}>
            <GradeIcon className="h-3 w-3" aria-hidden />
            {grade.label}
          </Badge>
        }
      />

      <div className="px-4 pb-4">
        <PlanRange
          commit={data.commit_display}
          base={data.base_display}
          prepare={data.prepare_display}
          confidence={data.confidence_level}
          position={
            data.commit != null && data.base != null && data.prepare != null
              ? data.prepare - data.commit
                ? (data.base - data.commit) / (data.prepare - data.commit)
                : 0.5
              : null
          }
        />

        {data.actions.length > 0 ? (
          <ol className="mt-4 space-y-2.5 border-t border-border pt-3">
            {data.actions.slice(0, 4).map((action, index) => (
              <li key={action.headline} className="flex gap-2.5">
                <span className="mt-px w-4 shrink-0 text-caption font-semibold text-text-muted num">
                  {index + 1}
                </span>
                <div className="min-w-0">
                  <p className="text-meta font-semibold text-text-primary">{action.headline}</p>
                  <p className="mt-0.5 text-caption text-text-secondary">{action.detail}</p>
                </div>
              </li>
            ))}
          </ol>
        ) : null}
      </div>
    </Card>
  );
}

function PlanRange({
  commit,
  base,
  prepare,
  confidence,
  position,
}: {
  commit: string | null;
  base: string | null;
  prepare: string | null;
  confidence: number | null;
  position: number | null;
}) {
  const level = confidence == null ? null : Math.round(confidence * 100);
  const at = position == null ? 0.5 : Math.min(Math.max(position, 0), 1);

  return (
    <div>
      <dl className="grid grid-cols-3 gap-2">
        <Figure label="Commit to" value={commit} className="text-positive" />
        <Figure label="Base case" value={base} className="text-text-primary" align="center" />
        <Figure label="Be ready for" value={prepare} className="text-warning" align="right" />
      </dl>

      <div className="relative mt-2 h-2.5" aria-hidden>
        <div className="absolute inset-0 flex overflow-hidden rounded-chip">
          <span className="bg-positive-soft" style={{ width: `${at * 100}%` }} />
          <span className="flex-1 bg-warning-soft" />
        </div>
        <span
          className="absolute top-[-3px] h-[calc(100%+6px)] w-px bg-text-primary"
          style={{ left: `${at * 100}%` }}
        />
      </div>

      <p className="mt-2 text-caption text-text-muted">
        Totals over the horizon.
        {level == null
          ? " Commit to the lower bound and hold capacity for the upper."
          : ` At a ${level}% interval, demand clears the lower bound in about ${Math.round(
              (1 - (1 - (confidence as number)) / 2) * 10,
            )} periods in ten. The upper bound sizes capacity, not commitment.`}
      </p>
    </div>
  );
}

function Figure({
  label,
  value,
  className,
  align = "left",
}: {
  label: string;
  value: string | null;
  className?: string;
  align?: "left" | "center" | "right";
}) {
  return (
    <div className={cn(align === "center" && "text-center", align === "right" && "text-right")}>
      <dt className="text-caption text-text-muted">{label}</dt>
      <dd className={cn("mt-0.5 text-kpi font-semibold num", className)}>{value ?? "—"}</dd>
    </div>
  );
}
