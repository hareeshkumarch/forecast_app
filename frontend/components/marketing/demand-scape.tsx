"use client";

import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import { buildScape, prismFaces, rangeLift, type Prism, type Tone } from "@/lib/demand-scape";
import {
  BAR_RISE,
  CAPTION_FADE,
  SHELL_EXPAND,
  barDelay,
  demoWalk,
  scapeTiming,
  shellDelay,
} from "@/lib/scape-motion";
import { useMotionReady } from "@/components/marketing/reveal";

const HISTORY = [72, 96, 84, 110, 91, 104, 81, 118, 89, 102, 78, 94, 72, 86, 68, 91, 74, 81, 64, 73, 61, 69, 58, 76, 67, 72];
const FUTURE = [86, 106, 78, 101, 72, 91, 68, 83, 61];

const PALETTE: Record<Tone, { front: string; side: string; top: string; stroke: string }> = {
  history: { front: "#151a16", side: "#3d433e", top: "#4a504b", stroke: "none" },
  future: { front: "#287b59", side: "#4b9478", top: "#74ad96", stroke: "none" },
  range: {
    front: "rgba(40,123,89,.08)",
    side: "rgba(40,123,89,.10)",
    top: "rgba(40,123,89,.12)",
    stroke: "#9ebfaf",
  },
};

const HINT = "Hover any week, or focus the chart and use the arrow keys";

type Readout = { label: string; point: string; range: string };

function readoutFor(step: number): Readout {
  if (step < HISTORY.length) {
    const value = HISTORY[step] ?? 0;
    return {
      label: `${HISTORY.length - step} weeks ago`,
      point: `${value} units sold`,
      range: "actual",
    };
  }
  const horizon = step - HISTORY.length + 1;
  const value = FUTURE[step - HISTORY.length] ?? 0;
  const spread = value * (rangeLift(horizon) - 1);
  return {
    label: `Week +${horizon}`,
    point: `${Math.round(value)} units`,
    range: `${Math.round(value - spread)} to ${Math.round(value + spread)}`,
  };
}

/*
 * The forecast readouts are laid out on shared columns. The chart walks these
 * weeks by itself on load, and "86 units" giving way to "106 units" is two
 * characters of difference that re-centres the whole line — the page moving on
 * its own, which is a layout shift on the way in and a flinch to look at. A
 * hover can afford it because a hover is the visitor's own doing; this cannot.
 * Equal character counts are equal widths in the mono face.
 */
const FORECAST_READOUTS = FUTURE.map((_, index) => readoutFor(HISTORY.length + index));
const COLUMN = {
  point: Math.max(...FORECAST_READOUTS.map((readout) => readout.point.length)),
  range: Math.max(...FORECAST_READOUTS.map((readout) => readout.range.length)),
};

function columned(readout: Readout): Readout {
  if (readout.range === "actual") return readout;
  return {
    label: readout.label,
    point: readout.point.padEnd(COLUMN.point),
    range: readout.range.padEnd(COLUMN.range),
  };
}

function Bar({ prism, onEnter }: { prism: Prism; onEnter: () => void }) {
  const faces = prismFaces(prism);
  const palette = PALETTE[prism.tone];
  const shell = prism.tone === "range";
  const timing = scapeTiming(HISTORY.length, FUTURE.length);
  const delay = shell
    ? shellDelay(prism.step, HISTORY.length, timing)
    : barDelay(prism.step, HISTORY.length, timing);

  return (
    <g
      className={shell ? "scape-bar scape-shell cursor-default" : "scape-bar cursor-default"}
      onMouseEnter={onEnter}
      style={
        {
          "--delay": `${delay}ms`,
          "--rise": `${BAR_RISE}ms`,
          "--expand": `${SHELL_EXPAND}ms`,
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

  const scape = useMemo(() => buildScape(HISTORY, FUTURE), []);
  const timing = useMemo(() => scapeTiming(HISTORY.length, FUTURE.length), []);

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
    if (!running || !motionReady) return;

    const walk = demoWalk(HISTORY.length, FUTURE.length, timing);
    const timers = walk.steps.map((step, index) =>
      window.setTimeout(() => {
        if (!taken.current) setHovered(step);
      }, walk.start + index * walk.interval),
    );

    // Let go at the end, so the hint the visitor is being taught comes back.
    timers.push(
      window.setTimeout(() => {
        if (!taken.current) setHovered(null);
      }, walk.release),
    );

    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [running, motionReady, timing]);

  const take = () => {
    taken.current = true;
  };

  const stage = motionReady ? (running ? "scape-running" : "scape-armed") : "";
  const spoken = hovered === null ? null : readoutFor(hovered);
  const readout = spoken === null ? null : columned(spoken);
  const marked = hovered === null ? null : scape.columns[hovered];

  const step = (delta: number) => {
    setKeyed(true);
    setHovered((current) => {
      const next = (current ?? -1) + delta;
      return Math.max(0, Math.min(scape.steps - 1, next < 0 ? 0 : next));
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
      setHovered(event.key === "Home" ? 0 : scape.steps - 1);
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
          viewBox={scape.viewBox}
          className={stage}
          role="img"
          aria-label={`${HISTORY.length} weeks of historical demand followed by a ${FUTURE.length}-week forecast and its possible range`}
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
            {scape.guides.map((guide) => (
              <line key={guide.key} x1={guide.x1} y1={guide.y1} x2={guide.x2} y2={guide.y2} />
            ))}
          </g>

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

          {scape.prisms.map((prism) => (
            <Bar
              key={prism.key}
              prism={prism}
              onEnter={() => {
                take();
                setHovered(prism.step);
              }}
            />
          ))}

          <g
            className="scape-caption"
            style={{ "--delay": `${timing.captionStart}ms`, "--caption-fade": `${CAPTION_FADE}ms` } as CSSProperties}
          >
            <line
              x1={scape.boundary.x1}
              y1={scape.boundary.y1}
              x2={scape.boundary.x2}
              y2={scape.boundary.y2}
              stroke="#616862"
              strokeDasharray="5 5"
              strokeWidth="1.5"
            />
            <g fill="#7d837d" fontFamily="var(--font-plex-mono)" fontSize="15" letterSpacing="1.2">
              {scape.labels.map((label) => (
                <text key={label.key} x={label.x} y={label.y} textAnchor={label.anchor}>
                  {label.text}
                </text>
              ))}
            </g>
          </g>
        </svg>
      </div>

      {/* Fixed height, so the readout appearing cannot move the page. Full
          width for the same reason horizontally: the line is centred inside a
          box that does not resize with what it is holding. */}
      <div className="mt-1 flex h-[26px] items-center justify-center">
        <p className="scape-readout w-full text-center font-mono text-site-caption" aria-hidden>
          {readout ? (
            <span className="whitespace-pre">
              <span className="text-[#111512]">{readout.label}</span>
              <span className="text-[#585e58]">
                {` · ${readout.point}`}
                {readout.range === "actual" ? "" : ` · range ${readout.range}`}
              </span>
            </span>
          ) : (
            <span className="text-[#858b85]">{HINT}</span>
          )}
        </p>
      </div>

      {/* Announced from the unpadded readout: the columns are a drawing
          concern, and a screen reader should not hear them. */}
      <p className="sr-only" aria-live="polite">
        {keyed && spoken
          ? `${spoken.label}, ${spoken.point}${spoken.range === "actual" ? "" : `, range ${spoken.range}`}`
          : ""}
      </p>

      <div className="mt-4 flex flex-wrap justify-center gap-x-8 gap-y-3 text-site-body text-[#656b65]">
        <span className="flex items-center gap-2.5"><span className="size-3 bg-[#151a16]" />What you sold</span>
        <span className="flex items-center gap-2.5"><span className="size-3 bg-[#287b59]" />What is coming</span>
        <span className="flex items-center gap-2.5"><span className="size-3 bg-[#c8ddd2]" />How far it could move</span>
      </div>
      <p className="mt-5 text-center text-site-body text-[#8a908a]">
        Two product groups shown — Chilled in front, Ambient behind.
      </p>
    </div>
  );
}
