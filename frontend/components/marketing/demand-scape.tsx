"use client";

import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import { buildScape, prismFaces, type Prism, type Tone } from "@/lib/demand-scape";
import {
  FUTURE_WEEKS,
  HISTORY_WEEKS,
  SERIES,
  columned,
  readoutFor,
  seriesDescription,
} from "@/lib/scape-data";
import { barDelay, demoWalk, scapeTiming, shellDelay, type ScapeTiming } from "@/lib/scape-motion";
import { useMotionReady } from "@/components/marketing/reveal";

const HINT = "Hover any week, or focus the chart and use the arrow keys";
const TOUCH_HINT = "Tap any week to inspect its forecast";

/* One series, drawn one way: nothing here depends on state, so it is measured
   once for the module rather than on every render. */
const SCAPE = buildScape(SERIES.layers, SERIES.growth);
const TIMING = scapeTiming(HISTORY_WEEKS, FUTURE_WEEKS);
const WALK = demoWalk(HISTORY_WEEKS, FUTURE_WEEKS, TIMING);

type Face = { front: string; side: string; top: string; stroke: string };

/*
 * One colour per tone, at one weight per row.
 *
 * The rows overlap by design — that is what makes the drawing read as depth —
 * and two rows painted identically collapse into a single silhouette the
 * moment they touch. The near line is at full strength and the line behind it
 * steps back, which is the depth cue the eye already knows and the only thing
 * that lets a visitor see there are two product lines here at all.
 */
const PALETTE: Record<Tone, Face[]> = {
  history: [
    { front: "#151a16", side: "#333a34", top: "#3f453f", stroke: "none" },
    { front: "#5c645d", side: "#767d76", top: "#828981", stroke: "none" },
  ],
  future: [
    { front: "#1d6b4b", side: "#357f5f", top: "#458d6e", stroke: "none" },
    { front: "#5ba488", side: "#74b09a", top: "#82b9a5", stroke: "none" },
  ],
  range: [
    {
      front: "rgba(40,123,89,.08)",
      side: "rgba(40,123,89,.10)",
      top: "rgba(40,123,89,.12)",
      stroke: "#9ebfaf",
    },
    {
      front: "rgba(40,123,89,.05)",
      side: "rgba(40,123,89,.07)",
      top: "rgba(40,123,89,.09)",
      stroke: "#bcd2c7",
    },
  ],
};

const FALLBACK: Face = { front: "#151a16", side: "#333a34", top: "#3f453f", stroke: "none" };

/** The nearest row's weight is the one a row beyond the palette falls back to,
 *  so a third product line would still draw rather than disappear. */
function faceFor(tone: Tone, row: number): Face {
  const weights = PALETTE[tone];
  return weights[Math.min(row, weights.length - 1)] ?? FALLBACK;
}

/* One entry in the key. The swatch carries a stripe per row, so a colour the
   chart shows in two weights is named once rather than twice. */
function Key({ weights, children }: { weights: string[]; children: ReactNode }) {
  return (
    <span className="flex items-center gap-2.5">
      <span className="flex size-3 shrink-0" aria-hidden>
        {weights.map((weight) => (
          <span key={weight} className="h-full flex-1" style={{ background: weight }} />
        ))}
      </span>
      {children}
    </span>
  );
}

function Bar({
  prism,
  timing,
  onEnter,
}: {
  prism: Prism;
  timing: ScapeTiming;
  onEnter: () => void;
}) {
  const faces = prismFaces(prism);
  const palette = faceFor(prism.tone, prism.row);
  const shell = prism.tone === "range";
  const delay = shell
    ? shellDelay(prism.step, HISTORY_WEEKS, timing)
    : barDelay(prism.step, HISTORY_WEEKS, timing);

  return (
    <g
      className={shell ? "scape-bar scape-shell cursor-default" : "scape-bar cursor-default"}
      /* Named rather than left to be recognised by its fill: the browser
         audits pick bars out of the page, and a colour is a thing that
         changes. */
      data-tone={prism.tone}
      data-row={prism.row}
      data-step={prism.step}
      onMouseEnter={onEnter}
      onPointerDown={onEnter}
      style={
        {
          "--delay": `${delay}ms`,
          "--rise": `${timing.rise}ms`,
          "--expand": `${timing.expand}ms`,
          "--shell-floor": prism.shellFloor,
        } as CSSProperties
      }
    >
      <polygon points={faces.front} fill={palette.front} stroke={palette.stroke} />
      <polygon points={faces.side} fill={palette.side} stroke={palette.stroke} />
      <polygon points={faces.top} fill={palette.top} stroke={palette.stroke} />
    </g>
  );
}

export function DemandScape() {
  const [hovered, setHovered] = useState<number | null>(null);
  const [keyed, setKeyed] = useState(false);
  const [running, setRunning] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const motionReady = useMotionReady();
  // Set the moment the visitor does anything to the chart themselves. From
  // then on it is theirs, and the demonstration never touches it again.
  const taken = useRef(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return;
        setRunning(true);
        observer.disconnect();
      },
      { threshold: 0.2 },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // Once built, the chart walks its own forecast and shows what the readout
  // gives, rather than only asking to be hovered. See `lib/scape-motion.ts`.
  useEffect(() => {
    if (!running || !motionReady || taken.current) return;

    const timers = WALK.steps.map((step, index) =>
      window.setTimeout(() => {
        if (!taken.current) setHovered(step);
      }, WALK.start + index * WALK.interval),
    );

    // Let go at the end, so the hint the visitor is being taught comes back.
    timers.push(
      window.setTimeout(() => {
        if (!taken.current) setHovered(null);
      }, WALK.release),
    );

    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [running, motionReady]);

  const take = () => {
    taken.current = true;
  };

  const stage = motionReady ? (running ? "scape-running" : "scape-armed") : "";
  const spoken = hovered === null ? null : readoutFor(hovered);
  const readout = spoken === null ? null : columned(spoken);
  const marked = hovered === null ? null : SCAPE.columns[hovered];

  const step = (delta: number) => {
    setKeyed(true);
    setHovered((current) => {
      const next = (current ?? -1) + delta;
      return Math.max(0, Math.min(SCAPE.steps - 1, next < 0 ? 0 : next));
    });
  };

  const onKeyDown = (event: ReactKeyboardEvent<SVGSVGElement>) => {
    take();
    const jump: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1 };
    if (event.key in jump) {
      event.preventDefault();
      step(jump[event.key] ?? 0);
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      setKeyed(true);
      setHovered(event.key === "Home" ? 0 : SCAPE.steps - 1);
      return;
    }
    if (event.key === "Escape") {
      setHovered(null);
    }
  };

  return (
    <div className="scape-frame" ref={ref}>
      <div className="relative">
        <svg
          viewBox={SCAPE.viewBox}
          className={stage}
          role="img"
          aria-label={seriesDescription()}
          tabIndex={0}
          onKeyDown={onKeyDown}
          onFocus={() => {
            take();
            setKeyed(true);
          }}
          onBlur={() => setHovered(null)}
          onMouseMove={() => {
            take();
            setKeyed(false);
          }}
          onMouseLeave={() => setHovered(null)}
          onTouchStart={take}
        >
          <g stroke="#cfd6cf" strokeWidth="1" opacity=".95">
            {SCAPE.guides.map((guide) => (
              <line key={guide.key} x1={guide.x1} y1={guide.y1} x2={guide.x2} y2={guide.y2} />
            ))}
          </g>

          {/* The marker spans both rows: a week is a week in every product
              line, and reading one of them alone is not what the chart is
              for. */}
          {marked ? (
            <rect
              className="scape-marker"
              x={marked.x}
              y={marked.y1}
              width={marked.width}
              height={marked.y2 - marked.y1}
              aria-hidden
            />
          ) : null}

          <g>
            {SCAPE.prisms.map((prism) => (
              <Bar
                key={prism.key}
                prism={prism}
                timing={TIMING}
                onEnter={() => {
                  take();
                  setHovered(prism.step);
                }}
              />
            ))}
          </g>

          <g
            className="scape-caption"
            style={
              {
                "--delay": `${TIMING.captionStart}ms`,
                "--caption-fade": `${TIMING.captionFade}ms`,
              } as CSSProperties
            }
          >
            <line
              x1={SCAPE.boundary.x1}
              y1={SCAPE.boundary.y1}
              x2={SCAPE.boundary.x2}
              y2={SCAPE.boundary.y2}
              stroke="#616862"
              strokeDasharray="5 5"
              strokeWidth="1.5"
            />
            <g fill="#7d837d" fontFamily="var(--font-plex-mono)" fontSize="15" letterSpacing="1.2">
              {SCAPE.labels.map((label) => (
                <text key={label.key} x={label.x} y={label.y} textAnchor={label.anchor}>
                  {label.text}
                </text>
              ))}
            </g>
            {/* Darker than the week captions: these name what the depth of the
                chart is, which is the part a visitor is least likely to guess
                and most likely to be told once. */}
            <g fill="#3f463f" fontFamily="var(--font-plex-mono)" fontSize="15" letterSpacing="1.2">
              {SCAPE.rowLabels.map((label) => (
                <text key={label.key} x={label.x} y={label.y} textAnchor={label.anchor}>
                  {label.text}
                </text>
              ))}
            </g>
          </g>
        </svg>
      </div>

      {/* Fixed height, so the readout appearing cannot move the page. Full
          width for the same reason horizontally: the lines are centred inside
          a box that does not resize with what it is holding. */}
      <div className="mt-1 flex min-h-[58px] items-center justify-center sm:h-[46px] sm:min-h-0">
        <p className="scape-readout w-full text-center font-mono text-site-caption" aria-hidden>
          <span className="block">
            {readout ? (
              <span className="hidden whitespace-pre sm:inline">
                <span className="text-[#111512]">{readout.label}</span>
                <span className="text-[#585e58]">
                  {` · ${readout.point}`}
                  {readout.range === "actual" ? "" : ` · range ${readout.range}`}
                </span>
              </span>
            ) : null}
            {spoken ? (
              <span className="text-[#585e58] sm:hidden">
                <span className="text-[#111512]">{spoken.label}</span>
                {` · ${spoken.point}`}
                {spoken.range === "actual" ? "" : ` · range ${spoken.range}`}
              </span>
            ) : (
              <>
                <span className="hidden text-[#858b85] sm:inline">{HINT}</span>
                <span className="text-[#858b85] sm:hidden">{TOUCH_HINT}</span>
              </>
            )}
          </span>
          {/* The same week one level down. Held on its own line rather than
              run on to the first: the split is what the two rows are for, and
              a line that long wraps differently on every phone. */}
          <span className="block min-h-[1.45em] whitespace-pre text-[#8a908a]">
            {readout ? readout.split : ""}
          </span>
        </p>
      </div>

      {/* Announced from the unpadded readout: the columns are a drawing
          concern, and a screen reader should not hear them. */}
      <p className="sr-only" aria-live="polite">
        {keyed && spoken
          ? `${spoken.label}, ${spoken.point}${spoken.range === "actual" ? "" : `, range ${spoken.range}`}, ${spoken.split}`
          : ""}
      </p>

      <div className="mt-4 flex flex-wrap justify-center gap-x-8 gap-y-3 text-site-body text-[#656b65]">
        <Key weights={PALETTE.history.map((face) => face.front)}>What you sold</Key>
        <Key weights={PALETTE.future.map((face) => face.front)}>What is coming</Key>
        <Key weights={["#c8ddd2"]}>How far it could move</Key>
      </div>
      <p className="mt-5 text-center text-site-body text-[#8a908a]">{SERIES.caption}</p>
    </div>
  );
}
