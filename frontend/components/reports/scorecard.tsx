"use client";

import { AlertTriangle, CheckCircle2, Gauge, Target } from "lucide-react";

import { Badge, Button, InlineError } from "@/components/ui/primitives";
import { useForecastMetrics, useScoreForecast, useScorecard } from "@/hooks/use-dashboard";
import { formatCompact, formatPercent, formatSignedPercent } from "@/lib/format";
import type { ForecastRun, Scorecard as ScorecardData } from "@/types/api";

/**
 * How a finished forecast did against what actually happened.
 *
 * Deliberately placed beside the backtest figures rather than instead of them:
 * the gap between "97% accurate in backtest" and "82% accurate in the event" is
 * the most useful thing on the page, and it only exists if both are shown.
 */
export function Scorecard({ run }: { run: ForecastRun }) {
  const { data, isLoading, isError, error, refetch } = useScorecard(
    run.status === "completed" ? run.id : null,
  );
  const score = useScoreForecast(run.id);

  if (run.status !== "completed") return null;

  if (isError) {
    return (
      <section className="mt-4 border-t border-border pt-3">
        <InlineError error={error} />
        <Button size="sm" variant="ghost" className="mt-2" onClick={() => void refetch()}>
          Try again
        </Button>
      </section>
    );
  }

  const card = data;
  const graded = Boolean(card?.scored);

  return (
    <section className="mt-4 border-t border-border pt-3" aria-label="Forecast versus actual">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Target aria-hidden className="size-3.5 text-text-muted" />
          <h3 className="text-caption font-semibold uppercase tracking-[0.04em] text-text-muted">
            Versus actual
          </h3>
          {graded && card ? (
            <Badge tone={verdictTone(card)}>
              {card.scored_periods} of {card.horizon} periods graded
            </Badge>
          ) : null}
        </div>

        <Button
          size="sm"
          variant={graded ? "ghost" : "secondary"}
          icon={Gauge}
          loading={score.isPending}
          disabled={isLoading}
          onClick={() => score.mutate(undefined)}
        >
          {graded ? "Re-score" : "Score against actuals"}
        </Button>
      </div>

      {isLoading ? (
        <p className="mt-2 text-caption text-text-muted">Checking…</p>
      ) : !card || !graded ? (
        <p className="mt-2 text-caption text-text-muted">
          {card?.blocked_reason ??
            "Not scored yet — no dataset covers the period this run forecast."}
        </p>
      ) : (
        <Graded card={card} run={run} />
      )}
    </section>
  );
}

function Graded({ card, run }: { card: ScorecardData; run: ForecastRun }) {
  // The backtest figure, fetched only once there is a realized one to set it
  // against — on its own it is already on the run's detail screen.
  const { data: metrics } = useForecastMetrics(run.id);
  const expected = metrics?.metrics.find((metric) => metric.name === "accuracy")?.value ?? null;

  return (
    <>
      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Figure
          label="Accuracy in the event"
          value={formatPercent(card.accuracy)}
          note={expected === null ? undefined : `${formatPercent(expected)} expected`}
          tone={accuracyTone(card.accuracy, expected)}
        />
        <Figure
          label="Ran high or low"
          value={formatSignedPercent(card.bias)}
          note={card.bias === null ? undefined : card.bias > 0 ? "over-forecast" : "under-forecast"}
        />
        <Figure
          label="Forecast"
          value={formatCompact(card.forecast_total, card.currency)}
          note={`${formatCompact(card.actual_total, card.currency)} actual`}
        />
        <Figure
          label={
            card.confidence_level === null
              ? "Inside the interval"
              : `Inside the ${Math.round(card.confidence_level * 100)}% interval`
          }
          value={card.coverage === null ? "—" : formatPercent(card.coverage, 0)}
          tone={card.intervals_held === null ? undefined : card.intervals_held ? "good" : "bad"}
        />
      </dl>

      <p className="mt-3 flex items-start gap-1.5 text-caption text-text-muted">
        {card.intervals_held === false || card.pending_periods > 0 ? (
          <AlertTriangle aria-hidden className="mt-px size-3 shrink-0 text-warning" />
        ) : (
          <CheckCircle2 aria-hidden className="mt-px size-3 shrink-0 text-positive" />
        )}
        <span>{summary(card)}</span>
      </p>
    </>
  );
}

function Figure({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note?: string;
  tone?: "good" | "bad";
}) {
  return (
    <div>
      <dt className="text-caption text-text-muted">{label}</dt>
      <dd
        className={`mt-0.5 text-meta font-semibold num ${
          tone === "good" ? "text-positive" : tone === "bad" ? "text-negative" : "text-text-primary"
        }`}
      >
        {value}
      </dd>
      {note ? <p className="text-caption text-text-muted num">{note}</p> : null}
    </div>
  );
}

/**
 * The sentence a reader takes away.
 *
 * Every clause is a different fault needing a different fix — a lean is not
 * scatter, and an interval that under-covers is not the same as being far out.
 */
function summary(card: ScorecardData): string {
  const parts: string[] = [];

  parts.push(
    `Measured against ${card.source_dataset_name ?? "later data"}` +
      (card.covered_through ? `, which runs to ${card.covered_through}.` : "."),
  );

  if (card.pending_periods > 0) {
    parts.push(
      `${card.pending_periods} period${card.pending_periods === 1 ? "" : "s"} of the horizon ` +
        "had not finished, so nothing is claimed about them.",
    );
  }
  if (card.intervals_held === false && card.confidence_level !== null) {
    parts.push(
      `The ${Math.round(card.confidence_level * 100)}% interval caught ` +
        `${formatPercent(card.coverage, 0)} of the actuals, so it was narrower than it claimed.`,
    );
  }
  if (card.unforecast_keys > 0) {
    parts.push(
      `${card.unforecast_keys} combination${card.unforecast_keys === 1 ? "" : "s"} appeared that ` +
        "this run never forecast; they count in the total but in no series.",
    );
  }

  return parts.join(" ");
}

function accuracyTone(
  realized: number | null,
  expected: number | null,
): "good" | "bad" | undefined {
  if (realized === null || expected === null) return undefined;
  return realized >= expected ? "good" : "bad";
}

function verdictTone(card: ScorecardData): "positive" | "warning" | "neutral" {
  if (card.pending_periods > 0) return "warning";
  return card.scored_periods > 0 ? "positive" : "neutral";
}
