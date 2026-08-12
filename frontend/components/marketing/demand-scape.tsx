"use client";

import { useState } from "react";

const HISTORY = [72, 96, 84, 110, 91, 104, 81, 118, 89, 102, 78, 94, 72, 86, 68, 91, 74, 81, 64, 73, 61, 69, 58, 76, 67, 72];
const FUTURE = [86, 106, 78, 101, 72, 91, 68, 83, 61];

type PrismProps = {
  x: number;
  y: number;
  height: number;
  tone: "history" | "future" | "range";
  onEnter?: () => void;
};

function Prism({ x, y, height, tone, onEnter }: PrismProps) {
  const width = 25;
  const depthX = 12;
  const depthY = 6;
  const top = y - height;
  const palette = {
    history: { front: "#151a16", side: "#3d433e", top: "#4a504b", stroke: "none" },
    future: { front: "#287b59", side: "#4b9478", top: "#74ad96", stroke: "none" },
    range: { front: "rgba(40,123,89,.08)", side: "rgba(40,123,89,.10)", top: "rgba(40,123,89,.12)", stroke: "#9ebfaf" },
  }[tone];

  return (
    <g className="demand-prism cursor-default" onMouseEnter={onEnter}>
      <polygon
        points={`${x},${top} ${x + width},${top} ${x + width},${y} ${x},${y}`}
        fill={palette.front}
        stroke={palette.stroke}
      />
      <polygon
        points={`${x + width},${top} ${x + width + depthX},${top - depthY} ${x + width + depthX},${y - depthY} ${x + width},${y}`}
        fill={palette.side}
        stroke={palette.stroke}
      />
      <polygon
        points={`${x},${top} ${x + depthX},${top - depthY} ${x + width + depthX},${top - depthY} ${x + width},${top}`}
        fill={palette.top}
        stroke={palette.stroke}
      />
    </g>
  );
}

export function DemandScape() {
  const [hovered, setHovered] = useState<number | null>(null);

  return (
    <div className="mx-auto w-full max-w-[1420px]">
      <div className="relative">
        <svg
          viewBox="0 0 1200 410"
          className="block h-auto w-full overflow-visible"
          role="img"
          aria-label="Twenty-six weeks of historical demand followed by a nine-week forecast and its possible range"
          onMouseLeave={() => setHovered(null)}
        >
          <g stroke="#cfd6cf" strokeWidth="1" opacity=".95">
            {Array.from({ length: 39 }, (_, index) => (
              <line
                key={`v-${index}`}
                x1={65 + index * 27}
                y1={120 + index * 7}
                x2={208 + index * 27}
                y2={190 + index * 7}
              />
            ))}
            {Array.from({ length: 8 }, (_, index) => (
              <line
                key={`h-${index}`}
                x1={65 + index * 24}
                y1={120 + index * 12}
                x2={1091 + index * 24}
                y2={386 + index * 12}
              />
            ))}
          </g>

          {[1, 0].map((row) => (
            <g key={row}>
              {HISTORY.map((height, index) => {
                const x = 98 + index * 27 + row * 38;
                const y = 174 + index * 7 - row * 34;
                return (
                  <Prism
                    key={`history-${row}-${index}`}
                    x={x}
                    y={y}
                    height={height * (row ? 0.72 : 0.54)}
                    tone="history"
                    onEnter={() => setHovered(index - HISTORY.length)}
                  />
                );
              })}

              {FUTURE.map((height, index) => {
                const sequence = HISTORY.length + index;
                const x = 98 + sequence * 27 + row * 38;
                const y = 174 + sequence * 7 - row * 34;
                return (
                  <g key={`future-${row}-${index}`}>
                    <Prism
                      x={x}
                      y={y}
                      height={(height + 37) * (row ? 0.72 : 0.54)}
                      tone="range"
                      onEnter={() => setHovered(index + 1)}
                    />
                    <Prism
                      x={x}
                      y={y}
                      height={height * (row ? 0.72 : 0.54)}
                      tone="future"
                      onEnter={() => setHovered(index + 1)}
                    />
                  </g>
                );
              })}
            </g>
          ))}

          <line x1="807" y1="88" x2="807" y2="303" stroke="#616862" strokeDasharray="5 5" strokeWidth="1.5" />
          <path d="M807 88 881 65" fill="none" stroke="#616862" strokeDasharray="5 5" strokeWidth="1.5" />

          <g fill="#7d837d" fontFamily="var(--font-plex-mono)" fontSize="14" letterSpacing="1.2">
            <text x="24" y="173">26 weeks ago</text>
            <text x="760" y="325">today</text>
            <text x="1002" y="397">+9 weeks</text>
          </g>

          {hovered !== null && (
            <g transform="translate(825 20)">
              <rect width="190" height="42" fill="#fafbf9" stroke="#cfd6cf" />
              <text x="14" y="26" fill="#303630" fontFamily="var(--font-plex-mono)" fontSize="13">
                {hovered > 0 ? `Week +${hovered} forecast` : "Historical demand"}
              </text>
            </g>
          )}
        </svg>
      </div>

      <p className="mt-1 text-center font-mono text-[12px] tracking-[0.06em] text-[#858b85] sm:text-[15px]">
        Hover any week to read it
      </p>
      <div className="mt-4 flex flex-wrap justify-center gap-x-8 gap-y-3 text-[14px] text-[#656b65] sm:text-[16px]">
        <span className="flex items-center gap-2.5"><span className="size-3 bg-[#151a16]" />What you sold</span>
        <span className="flex items-center gap-2.5"><span className="size-3 bg-[#287b59]" />What is coming</span>
        <span className="flex items-center gap-2.5"><span className="size-3 bg-[#c8ddd2]" />How far it could move</span>
      </div>
      <p className="mt-5 text-center text-[14px] text-[#8a908a] sm:text-[16px]">
        Two product groups shown — Chilled in front, Ambient behind.
      </p>
    </div>
  );
}
