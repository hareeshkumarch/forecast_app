"use client";

import { useId } from "react";

import { cn } from "@/lib/utils";

export function Sparkline({
  values,
  direction,
  width = 64,
  height = 20,
}: {
  values: number[];
  direction: "up" | "down" | "flat";
  width?: number;
  height?: number;
}) {
  const gradientId = useId();

  const finite = values.filter((value) => Number.isFinite(value));
  if (finite.length < 2) {
    return (
      <span className="inline-block text-caption text-text-muted" aria-label="no trend data">
        —
      </span>
    );
  }

  const min = Math.min(...finite);
  const max = Math.max(...finite);
  const span = max - min || 1;
  const padding = 2;
  const innerHeight = height - padding * 2;

  const points = finite.map((value, index) => {
    const x = (index / (finite.length - 1)) * width;
    const y = padding + innerHeight - ((value - min) / span) * innerHeight;
    return [x, y] as const;
  });

  const line = points.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`).join(" ");
  const area = `${line} L${width} ${height} L0 ${height} Z`;

  const tone =
    direction === "up"
      ? "text-positive"
      : direction === "down"
        ? "text-negative"
        : "text-text-muted";

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn("overflow-visible", tone)}
      role="img"
      aria-label={`Trend ${direction}`}
      focusable="false"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.18" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradientId})`} />
      <path
        d={line}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
