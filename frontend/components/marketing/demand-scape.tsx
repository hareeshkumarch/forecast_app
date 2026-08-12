"use client";

import type { CSSProperties } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import { buildScape, prismFaces, rangeLift, type Prism, type Tone } from "@/lib/demand-scape";
import {
  BAR_RISE,
  CAPTION_FADE,
  SHELL_EXPAND,
  barDelay,
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
  const [running, setRunning] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const motionReady = useMotionReady();

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

  const stage = motionReady ? (running ? "scape-running" : "scape-armed") : "";
  const readout = hovered === null ? null : readoutFor(hovered);

  return (
    <div className="mx-auto w-full max-w-[1420px]" ref={ref}>
      <div className="relative">
        <svg
          viewBox={scape.viewBox}
          className={`block h-auto w-full ${stage}`}
          role="img"
          aria-label={`${HISTORY.length} weeks of historical demand followed by a ${FUTURE.length}-week forecast and its possible range`}
          onMouseLeave={() => setHovered(null)}
        >
          <g stroke="#cfd6cf" strokeWidth="1" opacity=".95">
            {scape.guides.map((guide) => (
              <line key={guide.key} x1={guide.x1} y1={guide.y1} x2={guide.x2} y2={guide.y2} />
            ))}
          </g>

          {scape.prisms.map((prism) => (
            <Bar key={prism.key} prism={prism} onEnter={() => setHovered(prism.step)} />
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

      {/* Fixed height, so the readout appearing cannot move the page. */}
      <div className="mt-1 flex h-[26px] items-center justify-center">
        <p className="scape-readout font-mono text-site-caption" aria-live="polite">
          {readout ? (
            <>
              <span className="text-[#111512]">{readout.label}</span>
              <span className="text-[#585e58]">
                {` · ${readout.point}`}
                {readout.range === "actual" ? "" : ` · range ${readout.range}`}
              </span>
            </>
          ) : (
            <span className="text-[#858b85]">Hover any week to read it</span>
          )}
        </p>
      </div>

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
