"use client";

import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { buildScape, DEFAULT_CAMERA, prismFaces, projectPoint, type Camera, type Prism, type Tone } from "@/lib/demand-scape";
import { CAMERA_SWING, useScapeCamera } from "@/components/marketing/use-scape-camera";
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

const HINT = "Move to explore · Click a week to hold · Drag to rotate";
const TOUCH_HINT = "Swipe to rotate · Tap a week to hold";

const SCAPE = buildScape(SERIES.layers, SERIES.growth);
const TIMING = scapeTiming(HISTORY_WEEKS, FUTURE_WEEKS, SCAPE.rows);
const WALK = demoWalk(HISTORY_WEEKS, FUTURE_WEEKS, TIMING);
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
  camera,
}: {
  prism: Prism;
  timing: ScapeTiming;
  active: boolean;
  onEnter: () => void;
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
      <polygon points={faces.front} fill={shell ? palette.front : `color-mix(in srgb, ${palette.front} var(--scape-ink, 100%), var(--canvas))`} stroke={palette.stroke} />
      <polygon points={faces.side} fill={shell ? palette.side : `color-mix(in srgb, ${palette.side} var(--scape-ink, 100%), var(--canvas))`} stroke={palette.stroke} />
      <polygon points={faces.top} fill={shell ? palette.top : `color-mix(in srgb, ${palette.top} var(--scape-ink, 100%), var(--canvas))`} stroke={palette.stroke} />
      {!shell && active ? <polygon className="scape-selected-edge" points={faces.top} fill="none" stroke="var(--text-primary)" strokeWidth="1.2" pointerEvents="none" /> : null}
    </g>
  );
}

export function DemandScape() {
  const lightingId = useId().replace(/:/g, "");
  const [hovered, setHovered] = useState<number | null>(null);
  const [pinned, setPinned] = useState<number | null>(null);
  const [keyed, setKeyed] = useState(false);
  const [running, setRunning] = useState(false);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ id: number; x: number; y: number; camera: Camera; moved: boolean; step: number | null } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const motionReady = useMotionReady();
  const { camera, orbit, rotate, grab, rest } = useScapeCamera(motionReady);
  const taken = useRef(false);
  const viewCamera = camera;
  const scape = useMemo(() => buildScape(SERIES.layers, SERIES.growth, viewCamera), [viewCamera]);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) setRunning(true);
        else rest(false);
      },
      { threshold: 0.2 },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [rest]);

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
  const selected = pinned ?? hovered;
  const spoken = selected === null ? null : readoutFor(selected);
  const readout = spoken === null ? null : columned(spoken);
  const focused = scape.prisms.filter((prism) => prism.step === selected && prism.tone !== "range");
  const near = focused.find((prism) => prism.row === 0);
  const far = focused.find((prism) => prism.row === scape.rows - 1);
  const focusFloor = near && far ? prismFaces({ ...near, x: near.x - 5, z: near.z - 12, width: near.width + 10, depth: far.z - near.z + near.depth + 24 }, viewCamera).floor : null;

  const step = (delta: number) => {
    setKeyed(true);
    setPinned(null);
    setHovered((current) => {
      const next = (pinned ?? current ?? -1) + delta;
      return Math.max(0, Math.min(SCAPE.steps - 1, next < 0 ? 0 : next));
    });
  };

  const onPointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!event.isPrimary || event.button !== 0) return;
    take();
    const bar = (event.target as Element).closest("[data-step]");
    const selectedStep = bar?.getAttribute("data-step");
    drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, camera: grab(), moved: false, step: selectedStep == null ? null : Number(selectedStep) };
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
  };

  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const start = drag.current;
    if (!start) {
      if (event.pointerType !== "mouse" || !window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
      const box = event.currentTarget.getBoundingClientRect();
      orbit((event.clientX - box.left) / box.width * 2 - 1, (event.clientY - box.top) / box.height * 2 - 1);
      return;
    }
    if (start.id !== event.pointerId) return;
    const width = event.currentTarget.getBoundingClientRect().width;
    const dx = (event.clientX - start.x) / width;
    const dy = event.pointerType === "touch" ? 0 : (event.clientY - start.y) / width;
    if (Math.abs(event.clientX - start.x) + Math.abs(event.clientY - start.y) > 5) {
      start.moved = true;
      setHovered(null);
    }
    if (start.moved) rotate({ yaw: start.camera.yaw + dx * 1.4, pitch: start.camera.pitch - dy * 1.4 });
  };

  const endDrag = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (drag.current?.id !== event.pointerId) return;
    if (event.type === "pointerup" && !drag.current.moved && drag.current.step !== null) {
      const held = drag.current.step;
      setPinned((previous) => previous === held ? null : held);
    }
    drag.current = null;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };

  const onKeyDown = (event: ReactKeyboardEvent<SVGSVGElement>) => {
    take();
    if (event.shiftKey && event.key.startsWith("Arrow")) {
      event.preventDefault();
      rotate({ yaw: camera.yaw + (event.key === "ArrowRight" ? 0.03 : event.key === "ArrowLeft" ? -0.03 : 0),
        pitch: camera.pitch + (event.key === "ArrowUp" ? 0.03 : event.key === "ArrowDown" ? -0.03 : 0) });
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
      setPinned(null);
      setHovered(event.key === "Home" ? 0 : SCAPE.steps - 1);
      return;
    }
    if (event.key === "Escape") {
      setPinned(null);
      setHovered(null);
      rest();
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setPinned((previous) => previous === null ? hovered : null);
    }
  };

  return (
    <div className="scape-frame" ref={ref} data-dragging={dragging ? "true" : "false"} data-pinned={pinned === null ? undefined : "true"}>
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
          onPointerLeave={() => {
            setHovered(null);
            if (!drag.current) rest();
          }}
          onTouchStart={take}
          data-reading={selected === null ? undefined : "true"}
        >
          <defs>
            <radialGradient id={`${lightingId}-ground`}>
              <stop offset="0" stopColor="#75887a" stopOpacity="0.18" />
              <stop offset="1" stopColor="#75887a" stopOpacity="0" />
            </radialGradient>
          </defs>
          <polygon points={scape.ground} fill={`url(#${lightingId}-ground)`} />
          <g stroke="var(--scape-guide)" strokeWidth="1" opacity="0.45">
            {scape.guides.map((guide) => (
              <line key={guide.key} x1={guide.x1} y1={guide.y1} x2={guide.x2} y2={guide.y2} />
            ))}
          </g>

          {focusFloor ? <polygon className="scape-marker" points={focusFloor} stroke="var(--accent)" strokeWidth="1" aria-hidden /> : null}

          <g>
            {scape.prisms.map((prism) => (
              <Bar
                key={prism.key}
                prism={prism}
                timing={TIMING}
                active={prism.step === selected}
                camera={viewCamera}
                onEnter={() => {
                  take();
                  if (!drag.current) setHovered(prism.step);
                }}
              />
            ))}
          </g>

          <g className="scape-focus-points" pointerEvents="none" aria-hidden>
            {focused.map((prism) => {
              const point = projectPoint({ x: prism.x + prism.width / 2, y: prism.height, z: prism.z + prism.depth / 2 }, viewCamera);
              return <g key={prism.key}>
                <line x1={point.x} x2={point.x} y1={point.y - 22} y2={point.y - 5} stroke="var(--accent)" strokeWidth="1.2" />
                <circle cx={point.x} cy={point.y - 25} r="3" fill="var(--accent)" />
              </g>;
            })}
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
        <div className="scape-focus-note" data-visible={spoken ? "true" : undefined} aria-hidden>
          <span className="scape-focus-kicker">{pinned !== null ? "Week held" : "Inspecting"}{spoken ? ` / ${spoken.label}` : ""}</span>
          <strong>{spoken?.point ?? "Explore demand"}</strong>
          <span>{spoken?.range === "actual" ? "Recorded sales" : spoken ? `Expected range ${spoken.range}` : ""}</span>
        </div>
      </div>

      <p id={`${lightingId}-instructions`} className="sr-only">Move the mouse to explore the perspective. Drag to rotate or swipe horizontally on touch screens. Click or tap a week to hold it. Use Shift and arrow keys to rotate, arrow keys alone to inspect weeks, Enter to hold a week, and Escape to release it.</p>

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

      <div className="scape-tools">
        <button type="button" onClick={() => { take(); setHovered(null); setPinned(null); rotate(DEFAULT_CAMERA); }}>Reset view <span aria-hidden>↺</span></button>
        {pinned !== null ? <button type="button" onClick={() => { setPinned(null); setHovered(null); }}>Release week <span aria-hidden>×</span></button> : null}
      </div>

      <div className="scape-legend mt-4 flex flex-wrap justify-center gap-x-8 gap-y-3 text-site-body text-land-dim">
        <Key weights={PALETTE.history.map((face) => face.front)}>History</Key>
        <Key weights={PALETTE.future.map((face) => face.front)}>Forecast</Key>
        <Key weights={["var(--scape-shell-key)"]}>Expected range</Key>
      </div>
      <p className="scape-note mt-5 text-center text-site-body text-land-dim">{SERIES.caption}</p>
    </div>
  );
}
