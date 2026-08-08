"use client";

import { AlertTriangle, CheckCircle2, Gauge, Target, TrendingDown } from "lucide-react";

import { Badge, Button, InlineError } from "@/components/ui/primitives";
import { useForecastMetrics, useScoreForecast, useScorecard } from "@/hooks/use-dashboard";
import { formatCompact, formatPercent, formatSignedPercent } from "@/lib/format";
import type { ForecastRun, Scorecard as ScorecardData } from "@/types/api";

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

  const checkable = graded || Boolean(card?.source_dataset_id);

  return (
    <section className="mt-4 border-t border-border pt-3" aria-label="Forecast versus actual">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Target aria-hidden className="size-3.5 text-text-muted" />
          <h3 className="text-caption font-semibold uppercase tracking-[0.04em] text-text-muted">
            How it turned out
          </h3>
          {graded && card ? (
            <Badge tone={verdictTone(card)}>
              {card.scored_periods} of {card.horizon} periods checked
            </Badge>
          ) : null}
          {graded && card?.drifted ? (
            <Badge tone="negative">
              <TrendingDown aria-hidden className="size-3" />
              Drifting
            </Badge>
          ) : null}
        </div>

        <Button
          size="sm"
          variant={graded ? "ghost" : checkable ? "primary" : "secondary"}
          icon={Gauge}
          loading={score.isPending}
          disabled={isLoading || !checkable}
          title={
            checkable
              ? undefined
              : "Upload data covering the periods this forecast made, and this will grade it"
          }
          onClick={() => score.mutate(undefined)}
        >
          {graded ? "Check again" : "Check against real results"}
        </Button>
      </div>

      {isLoading ? (
        <p className="mt-2 text-caption text-text-muted">Looking for real results…</p>
      ) : !card || !graded ? (
        <p className="mt-2 text-caption text-text-muted">
          {card?.blocked_reason ??
            "Not checked yet — no data has arrived for the periods this forecast covers."}
        </p>
      ) : (
        <Graded card={card} run={run} />
      )}
    </section>
  );
}

export function ScoreLine({ runId }: { runId: string }) {
  const { data: card } = useScorecard(runId);
  const score = useScoreForecast(runId);

  if (!card) return null;

  const periods = `${card.scored_periods} of ${card.horizon} period${card.horizon === 1 ? "" : "s"}`;

  if (card.scored) {
    if (card.accuracy === null) {
      return (
        <p className="mt-1 flex flex-wrap items-center gap-1.5 text-caption text-text-muted">
          <Target className="h-3 w-3 shrink-0 text-warning" aria-hidden />
          <span>
            Checked over {periods}, but{" "}
            <span className="font-medium text-text-secondary">
              {card.source_dataset_name ?? "the data"}
            </span>{" "}
            recorded nothing in them, so there is no accuracy to report.
          </span>
        </p>
      );
    }

    return (
      <p className="mt-1 flex flex-wrap items-center gap-1.5 text-caption text-text-muted">
        <Target className="h-3 w-3 shrink-0 text-positive" aria-hidden />
        <span>
          Against what actually happened it was{" "}
          <span className="font-medium text-text-secondary num">{formatPercent(card.accuracy)}</span>{" "}
          accurate over {periods}.
        </span>
      </p>
    );
  }

  if (!card.source_dataset_id) return null;

  return (
    <p className="mt-1 flex flex-wrap items-center gap-1.5 text-caption text-text-muted">
      <Target className="h-3 w-3 shrink-0 text-accent" aria-hidden />
      <span>
        <span className="font-medium text-text-secondary">{card.source_dataset_name}</span> now
        covers the periods this forecast made.
      </span>
      <button
        type="button"
        disabled={score.isPending}
        onClick={() => score.mutate(undefined)}
        className="font-medium text-accent underline-offset-2 hover:underline disabled:opacity-60"
      >
        {score.isPending ? "Checking…" : "See how it turned out"}
      </button>
    </p>
  );
}

function Graded({ card, run }: { card: ScorecardData; run: ForecastRun }) {
  const { data: metrics } = useForecastMetrics(run.id);
  const expected = metrics?.metrics.find((metric) => metric.name === "accuracy")?.value ?? null;

  return (
    <>
      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Figure
          label="How accurate it was"
          value={formatPercent(card.accuracy)}
          note={expected === null ? undefined : `${formatPercent(expected)} was expected`}
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
              ? "Landed in range"
              : `Landed in the ${Math.round(card.confidence_level * 100)}% range`
          }
          value={card.coverage === null ? "—" : formatPercent(card.coverage, 0)}
          note={
            card.confidence_level === null
              ? undefined
              : `${Math.round(card.confidence_level * 100)}% was promised`
          }
          tone={card.intervals_held === null ? undefined : card.intervals_held ? "good" : "bad"}
        />
      </dl>

      <p className="mt-3 flex items-start gap-1.5 text-caption text-text-muted">
        {card.drifted || card.intervals_held === false || card.pending_periods > 0 ? (
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

function summary(card: ScorecardData): string {
  const parts: string[] = [];

  parts.push(
    `Checked against ${card.source_dataset_name ?? "your latest data"}` +
      (card.covered_through ? `, which runs to ${card.covered_through}.` : "."),
  );

  if (card.pending_periods > 0) {
    const many = card.pending_periods === 1;
    parts.push(
      `${card.pending_periods} more period${many ? " has" : "s have"} not finished yet, ` +
        `so ${many ? "it is" : "they are"} left out rather than half-counted.`,
    );
  }
  if (card.intervals_held === false && card.confidence_level !== null) {
    parts.push(
      `Results landed in the expected range only ${formatPercent(card.coverage, 0)} of the ` +
        `time instead of ${Math.round(card.confidence_level * 100)}%, so that range was too ` +
        "narrow — treat the next one as wider than it looks.",
    );
  }
  if (card.unforecast_keys > 0) {
    const one = card.unforecast_keys === 1;
    parts.push(
      `${card.unforecast_keys} new ${one ? "line" : "lines"} of business appeared that this ` +
        `forecast never covered, so ${one ? "it counts" : "they count"} in the total but in no ` +
        "single row below.",
    );
  }
  if (card.drifted) {
    parts.push(drift(card));
  }

  return parts.join(" ");
}

/**
 * The badge says a run has drifted; this says what that means for the reader.
 * A one-sided miss is worth refitting over, because it will keep happening —
 * unlike an equally large error that lands on both sides of the truth.
 */
function drift(card: ScorecardData): string {
  const signal = card.tracking_signal;

  if (signal !== null && Math.abs(signal) > 1) {
    const direction = signal > 0 ? "above" : "below";
    return (
      `It missed the same way in period after period — consistently ${direction} what ` +
      "happened, rather than scattering either side of it. That is drift, and it will not " +
      "correct itself: re-run on history that includes these periods."
    );
  }

  return (
    "The error is large enough that this run no longer describes the data it was fitted " +
    "on. Re-run it on history that includes these periods."
  );
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
