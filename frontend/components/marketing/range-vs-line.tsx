import type { CSSProperties } from "react";

import {
  FORECAST_DRAW,
  HISTORY_DRAW,
  OUTCOME_LAND,
  panelTiming,
} from "@/lib/compare-motion";
import { area, buildPanel, path } from "@/lib/range-vs-line";

const INK = "var(--compare-ink)";
const FOREST = "var(--compare-forecast)";
const RULE = "var(--compare-rule)";
const MUTED = "var(--compare-outcome)";

type PanelProps = {
  index: number;
  withBand: boolean;
  label: string;
  verdict: string;
  tone: "plain" | "forest";
};

function Panel({ index, withBand, label, verdict, tone }: PanelProps) {
  const panel = buildPanel(withBand);
  const stroke = tone === "forest" ? FOREST : INK;
  const timing = panelTiming(index);

  const pastClip = `compare-past-${index}`;
  const aheadClip = `compare-ahead-${index}`;

  return (
    <figure className="m-0 border border-land-brief-rule bg-land-brief">
      <figcaption className="border-b border-land-brief-rule px-5 py-3 font-mono text-site-caption uppercase tracking-[0.14em] text-land-dim">
        {label}
      </figcaption>

      <div className="px-5 pb-3 pt-5">
        <svg
          viewBox={`0 0 ${panel.width} ${panel.height}`}
          className="h-auto w-full"
          role="img"
          aria-label={
            withBand
              ? "A forecast drawn as a widening range, with the outcome landing inside it"
              : "A forecast drawn as a single line, with the outcome landing well below it"
          }
        >
          <defs>
            <clipPath id={pastClip} clipPathUnits="userSpaceOnUse">
              <rect
                className="draw-wipe"
                x={0}
                y={0}
                width={panel.split + 2}
                height={panel.height}
                style={
                  {
                    "--draw-delay": `${timing.history}ms`,
                    "--draw-duration": `${HISTORY_DRAW}ms`,
                  } as CSSProperties
                }
              />
            </clipPath>
            <clipPath id={aheadClip} clipPathUnits="userSpaceOnUse">
              <rect
                className="draw-wipe"
                x={panel.split}
                y={0}
                width={panel.width - panel.split}
                height={panel.height}
                style={
                  {
                    "--draw-delay": `${timing.forecast}ms`,
                    "--draw-duration": `${FORECAST_DRAW}ms`,
                  } as CSSProperties
                }
              />
            </clipPath>
          </defs>

          <line
            x1={panel.split}
            y1={10}
            x2={panel.split}
            y2={panel.baseline}
            stroke={RULE}
            strokeDasharray="3 4"
          />

          <g clipPath={`url(#${pastClip})`}>
            <path d={path(panel.history)} fill="none" stroke={INK} strokeWidth="2" />
          </g>

          <g clipPath={`url(#${aheadClip})`}>
            {panel.band ? <path d={area(panel.band)} fill={FOREST} fillOpacity="0.14" /> : null}
            <path
              d={path(panel.projection)}
              fill="none"
              stroke={stroke}
              strokeWidth="2"
              strokeDasharray={withBand ? undefined : "5 4"}
            />
          </g>

          <circle
            className="outcome-dot"
            cx={panel.outcome.x}
            cy={panel.outcome.y}
            r="4.5"
            fill={INK}
            style={
              {
                "--draw-delay": `${timing.outcome}ms`,
                "--draw-duration": `${OUTCOME_LAND}ms`,
              } as CSSProperties
            }
          />
          <circle
            className="outcome-ring"
            cx={panel.outcome.x}
            cy={panel.outcome.y}
            r="9"
            fill="none"
            stroke={INK}
            strokeWidth="1.5"
            opacity="0.35"
            style={
              {
                "--draw-delay": `${timing.outcome}ms`,
                "--draw-duration": `${OUTCOME_LAND}ms`,
              } as CSSProperties
            }
          />
        </svg>
      </div>

      <p className="border-t border-land-brief-rule px-5 py-4 text-site-body text-text-secondary">{verdict}</p>
    </figure>
  );
}

export function RangeVsLine() {
  return (
    <div>
      <div className="grid gap-5 sm:grid-cols-2">
        <Panel
          index={0}
          withBand={false}
          tone="plain"
          label="A single line"
          verdict="A point estimate alone does not show the expected spread of weekly sales."
        />
        <Panel
          index={1}
          withBand
          tone="forest"
          label="A line and its range"
          verdict="The same estimate with uncertainty bounds. Observed sales fall within the range."
        />
      </div>

      <p className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-2 font-mono text-site-caption uppercase tracking-[0.13em] text-land-dim">
        <span className="flex items-center gap-2">
          <span className="inline-block h-[2px] w-5" style={{ background: INK }} aria-hidden />
          What you sold
        </span>
        <span className="flex items-center gap-2">
          <span className="inline-block h-[2px] w-5" style={{ background: FOREST }} aria-hidden />
          What is coming
        </span>
        <span className="flex items-center gap-2">
          <span className="inline-block size-2.5 rounded-full" style={{ background: MUTED }} aria-hidden />
          What actually happened
        </span>
      </p>
    </div>
  );
}
