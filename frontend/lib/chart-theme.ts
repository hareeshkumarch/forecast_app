

import type { EChartsOption } from "echarts";


export const CHART_COLORS = {
  canvas: "#fbfaf7",
  surface: "#ffffff",
  surfaceMuted: "#f7f4ee",
  border: "#e7e1d7",
  borderStrong: "#d8d0c4",
  textPrimary: "#18202f",
  textSecondary: "#687080",
  textMuted: "#9297a1",
  accent: "#b87b19",
  accentSoft: "#fbf1df",
  navy: "#213b58",
  teal: "#527f79",
  gold: "#d19b3d",
  sand: "#e5c078",
  positive: "#338563",
  negative: "#d45b59",
  warning: "#bd7b21",
} as const;


export const CATEGORICAL_PALETTE = [
  CHART_COLORS.navy,
  CHART_COLORS.accent,
  CHART_COLORS.teal,
  CHART_COLORS.sand,
  CHART_COLORS.textSecondary,
] as const;

export const FONT_FAMILY =
  'var(--font-inter), ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

export const BASE_TEXT_STYLE = {
  fontFamily: FONT_FAMILY,
  fontSize: 11,
  color: CHART_COLORS.textSecondary,
} as const;


export const TOOLTIP_STYLE = {
  backgroundColor: CHART_COLORS.surface,
  borderColor: CHART_COLORS.border,
  borderWidth: 1,
  padding: [8, 10] as [number, number],
  extraCssText:
    "border-radius:9px;box-shadow:0 8px 24px rgba(24,32,47,0.10),0 2px 6px rgba(24,32,47,0.06);",
  textStyle: {
    fontFamily: FONT_FAMILY,
    fontSize: 11,
    color: CHART_COLORS.textPrimary,
  },
} as const;


export const SPLIT_LINE = {
  show: true,
  lineStyle: { color: CHART_COLORS.border, width: 1, type: "solid" as const },
};

export const AXIS_LABEL = {
  fontFamily: FONT_FAMILY,
  fontSize: 10,
  color: CHART_COLORS.textMuted,
} as const;

export const AXIS_LINE = {
  show: true,
  lineStyle: { color: CHART_COLORS.border, width: 1 },
};


export function baseChartOption(): EChartsOption {
  return {
    
    
    backgroundColor: "transparent",
    textStyle: BASE_TEXT_STYLE,
    animation: false,
    tooltip: { ...TOOLTIP_STYLE, confine: true },
  };
}


export function axisValueFormatter(currency = true) {
  const prefix = currency ? "$" : "";
  return (value: number): string => {
    const magnitude = Math.abs(value);
    const sign = value < 0 ? "-" : "";
    if (magnitude >= 1_000_000_000) return `${sign}${prefix}${(magnitude / 1e9).toFixed(1)}B`;
    if (magnitude >= 1_000_000) return `${sign}${prefix}${(magnitude / 1e6).toFixed(1)}M`;
    if (magnitude >= 1_000) return `${sign}${prefix}${(magnitude / 1e3).toFixed(0)}K`;
    return `${sign}${prefix}${magnitude.toFixed(0)}`;
  };
}


export function tooltipRow(color: string, label: string, value: string): string {
  return `
    <div style="display:flex;align-items:center;gap:6px;margin-top:3px;">
      <span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${color};"></span>
      <span style="color:${CHART_COLORS.textSecondary};">${label}</span>
      <span style="margin-left:auto;padding-left:14px;font-weight:600;color:${CHART_COLORS.textPrimary};">${value}</span>
    </div>`;
}

export function tooltipHeader(title: string): string {
  return `<div style="font-weight:600;color:${CHART_COLORS.textPrimary};font-size:11px;">${title}</div>`;
}
