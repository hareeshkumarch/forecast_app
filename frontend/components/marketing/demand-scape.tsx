"use client";

import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import { buildScape, prismFaces, type Prism, type Tone } from "@/lib/demand-scape";
import {
  DEFAULT_SCENARIO,
  SCENARIOS,
  columned,
  readoutFor,
  scenarioById,
} from "@/lib/scape-data";
import {
  REPLAY_PACE,
  barDelay,
  demoWalk,
  scapeTiming,
  shellDelay,
  type ScapeTiming,
} from "@/lib/scape-motion";
import { useMotionReady } from "@/components/marketing/reveal";
import { cn } from "@/lib/utils";

const HINT = "Hover any week, or focus the chart and use the arrow keys";
const TOUCH_HINT = "Tap any week to inspect its forecast";

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

function Bar({
  prism,
  historyLength,
  timing,
  onEnter,
}: {
  prism: Prism;
  historyLength: number;
  timing: ScapeTiming;
  onEnter: () => void;
}) {
  const faces = prismFaces(prism);
  const palette = PALETTE[prism.tone];
  const shell = prism.tone === "range";
  const delay = shell
    ? shellDelay(prism.step, historyLength, timing)
    : barDelay(prism.step, historyLength, timing);

  return (
    <g
      className={shell ? "scape-bar scape-shell cursor-default" : "scape-bar cursor-default"}
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
  const [scenarioId, setScenarioId] = useState(DEFAULT_SCENARIO.id);
  const [hovered, setHovered] = useState<number | null>(null);
  const [keyed, setKeyed] = useState(false);
  const [running, setRunning] = useState(false);
  // The opening build can take its time; everything after it is answering a
  // click, and runs the same choreography on a shorter clock.
  const [replaying, setReplaying] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const motionReady = useMotionReady();
  // Set the moment the visitor does anything to the chart themselves. From
  // then on it is theirs, and the demonstration never touches it again.
  const taken = useRef(false);

  const scenario = scenarioById(scenarioId);
  const historyLength = scenario.history.length;

  const scape = useMemo(
    () => buildScape(scenario.history, scenario.future, scenario.growth),
    [scenario],
  );
  const timing = useMemo(
    () =>
      scapeTiming(
        scenario.history.length,
        scenario.future.length,
        replaying ? REPLAY_PACE : 1,
      ),
    [scenario, replaying],
  );

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

    const walk = demoWalk(historyLength, scenario.future.length, timing);
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
  }, [running, motionReady, timing, historyLength, scenario.future.length]);

  const take = () => {
    taken.current = true;
  };

  const choose = (id: string) => {
    if (id === scenario.id) return;
    // Choosing data is the visitor doing the thing the demonstration was for.
    take();
    // The readout described a week of the series being replaced.
    setHovered(null);
    setReplaying(true);
    setScenarioId(id);
  };

  const stage = motionReady ? (running ? "scape-running" : "scape-armed") : "";
  const spoken = hovered === null ? null : readoutFor(scenario, hovered);
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
      {/*
       * Toggle buttons rather than tabs or radios: the chart below already
       * owns the arrow keys, and a widget that swallowed them to move between
       * its own options would take them away from the thing worth exploring.
       */}
      <div
        role="group"
        aria-label="Example demand to draw"
        className="mb-5 flex flex-wrap items-center justify-center gap-2"
      >
        {SCENARIOS.map((option) => (
          <button
            key={option.id}
            type="button"
            aria-pressed={option.id === scenario.id}
            onClick={() => choose(option.id)}
            className={cn(
              "scape-chip border px-4 py-2 font-mono text-site-caption uppercase tracking-[0.12em]",
              option.id === scenario.id
                ? "border-[#111512] bg-[#111512] text-white"
                : "border-[#cfd5cf] bg-[#fafbf9] text-[#4e554e] hover:border-[#8f9a90] hover:text-[#111512]",
            )}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="relative">
        <svg
          viewBox={scape.viewBox}
          className={stage}
          role="img"
          aria-label={`${scenario.label}: ${historyLength} weeks of historical demand followed by a ${scenario.future.length}-week forecast and its possible range`}
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

          {/*
           * Keyed on the scenario, so choosing one remounts the bars and the
           * build sequence runs again from the start. A CSS animation cannot
           * be replayed in place without removing the element that carries it,
           * and running it again is the right thing to show anyway: picking a
           * series is asking for a forecast, and this is the chart making one.
           */}
          <g key={scenario.id}>
            {scape.prisms.map((prism) => (
              <Bar
                key={prism.key}
                prism={prism}
                historyLength={historyLength}
                timing={timing}
                onEnter={() => {
                  take();
                  setHovered(prism.step);
                }}
              />
            ))}
          </g>

          {/* Outside that key: the axis and the today line are the same in
              every scenario, and should not blink on each choice. */}
          <g
            className="scape-caption"
            style={
              {
                "--delay": `${timing.captionStart}ms`,
                "--caption-fade": `${timing.captionFade}ms`,
              } as CSSProperties
            }
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
      <div className="mt-1 flex min-h-[42px] items-center justify-center sm:h-[26px] sm:min-h-0">
        <p className="scape-readout w-full text-center font-mono text-site-caption" aria-hidden>
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
      <p className="mt-5 text-center text-site-body text-[#8a908a]">{scenario.caption}</p>
    </div>
  );
}
