"use client";

import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { buildScape, DEFAULT_CAMERA, prismFaces, projectPoint, type Camera, type Prism, type Tone } from "@/lib/demand-scape";
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

const HINT = "Drag to rotate · Hover a week to inspect";
const TOUCH_HINT = "Swipe sideways to rotate · Tap a week to inspect";

const SCAPE = buildScape(SERIES.layers, SERIES.growth);
const TIMING = scapeTiming(HISTORY_WEEKS, FUTURE_WEEKS, SCAPE.rows);
const WALK = demoWalk(HISTORY_WEEKS, FUTURE_WEEKS, TIMING);
const CAMERA_SWING = { yaw: 0.18, pitch: 0.09 };
const ORBIT_BOUNDS = [-1, 1].flatMap((yaw) => [-1, 1].map((pitch) =>
  buildScape(SERIES.layers, SERIES.growth, {
    yaw: DEFAULT_CAMERA.yaw + yaw * CAMERA_SWING.yaw,
    pitch: DEFAULT_CAMERA.pitch + pitch * CAMERA_SWING.pitch,
  }).viewBox.split(" ").map(Number),
));
const LEFT = Math.min(...ORBIT_BOUNDS.map((box) => box[0]!)) - 20;
const TOP = Math.min(...ORBIT_BOUNDS.map((box) => box[1]!)) - 30;
const VIEW_BOX = `${LEFT} ${TOP} ${Math.max(...ORBIT_BOUNDS.map((box) => box[0]! + box[2]!)) - LEFT + 20} ${Math.max(...ORBIT_BOUNDS.map((box) => box[1]! + box[3]!)) - TOP + 30}`;

type Face = { front: string; side: string; top: string; stroke: string };

const PALETTE: Record<Tone, Face[]> = {
  history: [
    {
      front: "var(--scape-sold-near)",
      side: "var(--scape-sold-near-side)",
      top: "var(--scape-sold-near-top)",
      stroke: "none",
    },
    {
      front: "var(--scape-sold-far)",
      side: "var(--scape-sold-far-side)",
      top: "var(--scape-sold-far-top)",
      stroke: "none",
    },
  ],
  future: [
    {
      front: "var(--scape-next-near)",
      side: "var(--scape-next-near-side)",
      top: "var(--scape-next-near-top)",
      stroke: "none",
    },
    {
      front: "var(--scape-next-far)",
      side: "var(--scape-next-far-side)",
      top: "var(--scape-next-far-top)",
      stroke: "none",
    },
  ],
  range: [
    {
      front: "var(--scape-shell-near)",
      side: "var(--scape-shell-near-side)",
      top: "var(--scape-shell-near-top)",
      stroke: "var(--scape-shell-near-line)",
    },
    {
      front: "var(--scape-shell-far)",
      side: "var(--scape-shell-far-side)",
      top: "var(--scape-shell-far-top)",
      stroke: "var(--scape-shell-far-line)",
    },
  ],
};

const FALLBACK: Face = {
  front: "var(--scape-sold-near)",
  side: "var(--scape-sold-near-side)",
  top: "var(--scape-sold-near-top)",
  stroke: "none",
};

function faceFor(tone: Tone, row: number): Face {
  const weights = PALETTE[tone];
  return weights[Math.min(row, weights.length - 1)] ?? FALLBACK;
}

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
  active,
  onEnter,
  lightingId,
  camera,
}: {
  prism: Prism;
  timing: ScapeTiming;
  active: boolean;
  onEnter: () => void;
  lightingId: string;
  camera: Camera;
}) {
  const faces = prismFaces(prism, camera);
  const palette = faceFor(prism.tone, prism.row);
  const shell = prism.tone === "range";
  const delay = shell
    ? shellDelay(prism.step, HISTORY_WEEKS, timing, prism.row, SCAPE.rows)
    : barDelay(prism.step, HISTORY_WEEKS, timing, prism.row, SCAPE.rows);

  return (
    <g
      className={shell ? "scape-bar scape-shell" : "scape-bar"}
      data-active={active ? "true" : undefined}
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
      {shell ? <polygon className="scape-crown" points={faces.top} fill="none" stroke="var(--accent)" strokeWidth="1.5" style={{ "--pulse-delay": `${prism.horizon * -220}ms` } as CSSProperties} /> : null}
      {!shell ? <g pointerEvents="none">
        <polygon points={faces.front} fill={`url(#${lightingId}-front)`} />
        <polygon points={faces.side} fill={`url(#${lightingId}-side)`} />
        <polygon points={faces.top} fill={`url(#${lightingId}-top)`} stroke="rgba(235,255,240,0.28)" strokeWidth="0.7" />
      </g> : null}
    </g>
  );
}

export function DemandScape() {
  const lightingId = useId().replace(/:/g, "");
  const [hovered, setHovered] = useState<number | null>(null);
  const [keyed, setKeyed] = useState(false);
  const [running, setRunning] = useState(false);
  const [visible, setVisible] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [camera, setCamera] = useState<Camera>(DEFAULT_CAMERA);
  const drag = useRef<{ id: number; x: number; y: number; camera: Camera } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const motionReady = useMotionReady();
  const taken = useRef(false);
  const viewCamera = camera;
  const scape = useMemo(() => buildScape(SERIES.layers, SERIES.growth, viewCamera), [viewCamera]);
  const moving = motionReady && visible;
  const trails = useMemo(() => SERIES.layers.map((_, row) => {
    const points = scape.prisms.filter((prism) => prism.row === row && prism.tone !== "range")
      .sort((a, b) => a.step - b.step)
      .map((prism) => projectPoint({ x: prism.x + prism.width / 2, y: prism.height + 14, z: prism.z + prism.depth / 2 }, viewCamera));
    return points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
  }), [scape, viewCamera]);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        setVisible(Boolean(entry?.isIntersecting));
        if (entry?.isIntersecting) setRunning(true);
      },
      { threshold: 0.2 },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!running || !motionReady || taken.current) return;

    const timers = WALK.steps.map((step, index) =>
      window.setTimeout(() => {
        if (!taken.current) setHovered(step);
      }, WALK.start + index * WALK.interval),
    );

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
  const marked = hovered === null ? null : scape.columns[hovered];

  const step = (delta: number) => {
    setKeyed(true);
    setHovered((current) => {
      const next = (current ?? -1) + delta;
      return Math.max(0, Math.min(SCAPE.steps - 1, next < 0 ? 0 : next));
    });
  };

  const rotate = (yaw: number, pitch: number) => setCamera({
    yaw: Math.max(DEFAULT_CAMERA.yaw - CAMERA_SWING.yaw, Math.min(DEFAULT_CAMERA.yaw + CAMERA_SWING.yaw, yaw)),
    pitch: Math.max(DEFAULT_CAMERA.pitch - CAMERA_SWING.pitch, Math.min(DEFAULT_CAMERA.pitch + CAMERA_SWING.pitch, pitch)),
  });

  const onPointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!event.isPrimary || event.button !== 0) return;
    take();
    drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, camera };
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
  };

  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const start = drag.current;
    if (!start || start.id !== event.pointerId) return;
    const width = event.currentTarget.getBoundingClientRect().width;
    const dx = (event.clientX - start.x) / width;
    const dy = event.pointerType === "touch" ? 0 : (event.clientY - start.y) / width;
    if (Math.abs(dx) + Math.abs(dy) > 0.005) setHovered(null);
    rotate(start.camera.yaw + dx * 1.4, start.camera.pitch - dy * 1.4);
  };

  const endDrag = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (drag.current?.id !== event.pointerId) return;
    drag.current = null;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };

  const onKeyDown = (event: ReactKeyboardEvent<SVGSVGElement>) => {
    take();
    if (event.shiftKey && event.key.startsWith("Arrow")) {
      event.preventDefault();
      rotate(camera.yaw + (event.key === "ArrowRight" ? 0.03 : event.key === "ArrowLeft" ? -0.03 : 0),
        camera.pitch + (event.key === "ArrowUp" ? 0.03 : event.key === "ArrowDown" ? -0.03 : 0));
      return;
    }
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
    <div className="scape-frame" ref={ref} data-moving={moving ? "true" : "false"} data-dragging={dragging ? "true" : "false"}>
      <div className="relative">
        <svg
          viewBox={VIEW_BOX}
          className={stage}
          role="img"
          aria-label={seriesDescription()}
          tabIndex={0}
          onKeyDown={onKeyDown}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onLostPointerCapture={endDrag}
          aria-describedby={`${lightingId}-instructions`}
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
          data-reading={hovered === null ? undefined : "true"}
        >
          <defs>
            <linearGradient id={`${lightingId}-front`} x1="0" y1="0" x2="0.2" y2="1">
              <stop offset="0" stopColor="#ffffff" stopOpacity="0.35" />
              <stop offset="0.25" stopColor="#ffffff" stopOpacity="0.02" />
              <stop offset="0.45" stopColor="#000000" stopOpacity="0.06" />
              <stop offset="1" stopColor="#000000" stopOpacity="0.42" />
            </linearGradient>
            <linearGradient id={`${lightingId}-side`} x1="0" y1="0" x2="1" y2="0.7">
              <stop offset="0" stopColor="#000000" stopOpacity="0.12" />
              <stop offset="1" stopColor="#000000" stopOpacity="0.5" />
            </linearGradient>
            <linearGradient id={`${lightingId}-top`} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#ffffff" stopOpacity="0.32" />
              <stop offset="1" stopColor="#ffffff" stopOpacity="0.02" />
            </linearGradient>
            <radialGradient id={`${lightingId}-ground`}>
              <stop offset="0" stopColor="#75887a" stopOpacity="0.18" />
              <stop offset="1" stopColor="#75887a" stopOpacity="0" />
            </radialGradient>
            <filter id={`${lightingId}-shadow`} x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="4" />
            </filter>
            <filter id={`${lightingId}-contact`} x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="1.8" />
            </filter>
          </defs>
          <polygon points={scape.ground} fill="var(--scape-guide)" opacity="0.16" transform="translate(0 12)" />
          <polygon points={scape.ground} fill={`url(#${lightingId}-ground)`} stroke="var(--scape-guide)" strokeWidth="0.8" />
          <g stroke="var(--scape-guide)" strokeWidth="1" opacity=".95">
            {scape.guides.map((guide) => (
              <line key={guide.key} x1={guide.x1} y1={guide.y1} x2={guide.x2} y2={guide.y2} />
            ))}
          </g>

          <g pointerEvents="none" aria-hidden>
            {scape.prisms.filter((prism) => prism.tone !== "range").map((prism) => {
              const faces = prismFaces(prism, viewCamera);
              return <g key={prism.key}>
                <polygon points={faces.shadow} fill="#000000" opacity="0.24" filter={`url(#${lightingId}-shadow)`} />
                <polygon points={faces.floor} fill="#000000" opacity="0.65" filter={`url(#${lightingId}-contact)`} />
              </g>;
            })}
          </g>

          {marked
            ? marked.bands.map((band) => (
                <rect
                  key={band.key}
                  className="scape-marker"
                  x={band.x}
                  y={band.y1}
                  width={band.width}
                  height={band.y2 - band.y1}
                  aria-hidden
                />
              ))
            : null}

          <g>
            {scape.prisms.map((prism) => (
              <Bar
                key={prism.key}
                prism={prism}
                timing={TIMING}
                active={prism.step === hovered}
                lightingId={lightingId}
                camera={viewCamera}
                onEnter={() => {
                  take();
                  if (!drag.current) setHovered(prism.step);
                }}
              />
            ))}
          </g>

          <g className="scape-streams" fill="none" pointerEvents="none" aria-hidden>
            {trails.map((path, row) => <g key={row}>
              <path d={path} stroke="var(--accent)" strokeWidth="1" opacity="0.25" />
              <path className="scape-current" d={path} pathLength="100" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" strokeDasharray="3 97" style={{ "--pulse-delay": `${row * -2400}ms` } as CSSProperties} />
            </g>)}
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
              x1={scape.boundary.x1}
              y1={scape.boundary.y1}
              x2={scape.boundary.x2}
              y2={scape.boundary.y2}
              stroke="var(--scape-axis)"
              strokeDasharray="5 5"
              strokeWidth="1.5"
            />
            <g fill="var(--scape-week)" fontFamily="var(--font-plex-mono)" fontSize="15" letterSpacing="1.2">
              {scape.labels.map((label) => (
                <text key={label.key} x={label.x} y={label.y} textAnchor={label.anchor}>
                  {label.text}
                </text>
              ))}
            </g>
            <g fill="var(--scape-row-name)" fontFamily="var(--font-plex-mono)" fontSize="15" letterSpacing="1.2">
              {scape.rowLabels.map((label) => (
                <text key={label.key} x={label.x} y={label.y} textAnchor={label.anchor}>
                  {label.text}
                </text>
              ))}
            </g>
          </g>
        </svg>
      </div>

      <p id={`${lightingId}-instructions`} className="sr-only">Drag to rotate. Swipe horizontally on touch screens. Use Shift and arrow keys to rotate, or arrow keys alone to inspect weeks.</p>

      <div className="mt-1 flex min-h-[58px] items-center justify-center sm:h-[46px] sm:min-h-0">
        <p className="scape-readout w-full text-center font-mono text-site-caption" aria-hidden>
          <span className="block">
            {readout ? (
              <span className="hidden whitespace-pre sm:inline">
                <span className="text-text-primary">{readout.label}</span>
                <span className="text-text-secondary">
                  {` · ${readout.point}`}
                  {readout.range === "actual" ? "" : ` · range ${readout.range}`}
                </span>
              </span>
            ) : null}
            {spoken ? (
              <span className="text-text-secondary sm:hidden">
                <span className="text-text-primary">{spoken.label}</span>
                {` · ${spoken.point}`}
                {spoken.range === "actual" ? "" : ` · range ${spoken.range}`}
              </span>
            ) : (
              <>
                <span className="hidden text-land-dim sm:inline">{HINT}</span>
                <span className="text-land-dim sm:hidden">{TOUCH_HINT}</span>
              </>
            )}
          </span>
          <span className="block min-h-[1.45em] whitespace-pre text-land-dim">
            {readout ? readout.split : ""}
          </span>
        </p>
      </div>

      <p className="sr-only" aria-live="polite">
        {keyed && spoken
          ? `${spoken.label}, ${spoken.point}${spoken.range === "actual" ? "" : `, range ${spoken.range}`}, ${spoken.split}`
          : ""}
      </p>

      <div className="scape-legend mt-4 flex flex-wrap justify-center gap-x-8 gap-y-3 text-site-body text-land-dim">
        <Key weights={PALETTE.history.map((face) => face.front)}>History</Key>
        <Key weights={PALETTE.future.map((face) => face.front)}>Forecast</Key>
        <Key weights={["var(--scape-shell-key)"]}>Expected range</Key>
      </div>
      <p className="scape-note mt-5 text-center text-site-body text-land-dim">{SERIES.caption}</p>
    </div>
  );
}
