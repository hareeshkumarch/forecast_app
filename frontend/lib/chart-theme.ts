import type { EChartsOption } from "echarts";

/**
 * Charts paint on a canvas, so they cannot inherit CSS variables the way the
 * DOM does. Colours are read from the document at build-option time instead,
 * which keeps them correct in either theme; the literals below are the light
 * palette and serve as the server-render fallback.
 */
const FALLBACK = {
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

const VARIABLES: Record<keyof typeof FALLBACK, string> = {
  canvas: "--canvas",
  surface: "--surface",
  surfaceMuted: "--surface-muted",
  border: "--border",
  borderStrong: "--border-strong",
  textPrimary: "--text-primary",
  textSecondary: "--text-secondary",
  textMuted: "--text-muted",
  accent: "--accent",
  accentSoft: "--accent-soft",
  navy: "--navy",
  teal: "--teal",
  gold: "--gold",
  sand: "--sand",
  positive: "--positive",
  negative: "--negative",
  warning: "--warning",
};

export type ChartPalette = Record<keyof typeof FALLBACK, string>;

export function chartColors(): ChartPalette {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return { ...FALLBACK };
  }

  const styles = window.getComputedStyle(document.documentElement);
  const resolved = {} as ChartPalette;

  for (const [key, variable] of Object.entries(VARIABLES) as [
    keyof typeof FALLBACK,
    string,
  ][]) {
    resolved[key] = styles.getPropertyValue(variable).trim() || FALLBACK[key];
  }
  return resolved;
}

export function categoricalPalette(colors: ChartPalette = chartColors()): string[] {
  return [colors.navy, colors.accent, colors.teal, colors.sand, colors.textSecondary];
}

export const FONT_FAMILY =
  'var(--font-inter), ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

export function baseTextStyle(colors: ChartPalette = chartColors()) {
  return { fontFamily: FONT_FAMILY, fontSize: 11, color: colors.textSecondary };
}

export function tooltipStyle(colors: ChartPalette = chartColors()) {
  return {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    padding: [8, 10] as [number, number],
    extraCssText: "border-radius:9px;box-shadow:var(--shadow-popover);",
    textStyle: { fontFamily: FONT_FAMILY, fontSize: 11, color: colors.textPrimary },
  };
}

export function splitLine(colors: ChartPalette = chartColors()) {
  return { show: true, lineStyle: { color: colors.border, width: 1, type: "solid" as const } };
}

export function axisLabel(colors: ChartPalette = chartColors()) {
  return { fontFamily: FONT_FAMILY, fontSize: 10, color: colors.textMuted };
}

export function axisLine(colors: ChartPalette = chartColors()) {
  return { show: true, lineStyle: { color: colors.border, width: 1 } };
}

export function baseChartOption(colors: ChartPalette = chartColors()): EChartsOption {
  return {
    backgroundColor: "transparent",
    textStyle: baseTextStyle(colors),
    animation: false,
    tooltip: { ...tooltipStyle(colors), confine: true },
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

export function tooltipRow(
  color: string,
  label: string,
  value: string,
  colors: ChartPalette = chartColors(),
): string {
  return `
    <div style="display:flex;align-items:center;gap:6px;margin-top:3px;">
      <span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${color};"></span>
      <span style="color:${colors.textSecondary};">${label}</span>
      <span style="margin-left:auto;padding-left:14px;font-weight:600;color:${colors.textPrimary};">${value}</span>
    </div>`;
}

export function tooltipHeader(title: string, colors: ChartPalette = chartColors()): string {
  return `<div style="font-weight:600;color:${colors.textPrimary};font-size:11px;">${title}</div>`;
}
