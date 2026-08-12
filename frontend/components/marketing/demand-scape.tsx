"use client";

import { useMemo, useState } from "react";

import { buildScape, prismFaces, type Prism, type Tone } from "@/lib/demand-scape";

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

function Prisms({ prism, onEnter }: { prism: Prism; onEnter: () => void }) {
  const faces = prismFaces(prism);
  const palette = PALETTE[prism.tone];

  return (
    <g className="demand-prism cursor-default" onMouseEnter={onEnter}>
      <polygon points={faces.front} fill={palette.front} stroke={palette.stroke} />
      <polygon points={faces.side} fill={palette.side} stroke={palette.stroke} />
      <polygon points={faces.top} fill={palette.top} stroke={palette.stroke} />
    </g>
  );
}

export function DemandScape() {
  const [hovered, setHovered] = useState<number | null>(null);
  const scape = useMemo(() => buildScape(HISTORY, FUTURE), []);

  return (
    <div className="mx-auto w-full max-w-[1420px]">
      <div className="relative">
        <svg
          viewBox={scape.viewBox}
          className="block h-auto w-full"
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
            <Prisms
              key={prism.key}
              prism={prism}
              onEnter={() =>
                setHovered(
                  prism.step < HISTORY.length
                    ? prism.step - HISTORY.length
                    : prism.step - HISTORY.length + 1,
                )
              }
            />
          ))}

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
        </svg>
      </div>

      <p className="mt-1 text-center font-mono text-site-caption text-[#858b85]" aria-live="polite">
        {hovered === null
          ? "Hover any week to read it"
          : hovered > 0
            ? `Week +${hovered} forecast`
            : `${-hovered} weeks ago`}
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
