import { formatCompact } from "@/lib/format";

const FALLBACK = {
  canvas: "#f6f8fb",
  surface: "#ffffff",
  surfaceMuted: "#eff3f9",
  border: "#e0e6f0",
  borderStrong: "#c9d3e2",
  textPrimary: "#111826",
  textSecondary: "#586274",
  textMuted: "#8a93a3",
  accent: "#2c5fa8",
  accentSoft: "#e9f0fa",
  navy: "#1d3c68",
  teal: "#3d868c",
  gold: "#b8862f",
  sand: "#9db2cf",
  positive: "#1a7f5a",
  negative: "#c94a4a",
  warning: "#a9721a",
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

export function axisValueFormatter(currency = true) {
  return (value: number): string => formatCompact(value, currency);
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
