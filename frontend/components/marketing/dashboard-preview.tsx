import {
  Activity,
  CreditCard,
  Database,
  FileBarChart2,
  FileSpreadsheet,
  Gauge,
  LayoutDashboard,
  Layers,
  Lightbulb,
  Settings,
  Sparkles,
  Target,
  TrendingDown,
  TrendingUp,
  AlertTriangle,
  type LucideIcon,
} from "lucide-react";
import type { CSSProperties } from "react";

import { Reveal } from "@/components/marketing/reveal";
import { cn } from "@/lib/utils";

/*
 * A still of the product, built from the same tokens the product is built
 * from — so when the palette moves, the picture of it moves too. It is
 * decorative: a single aria-label stands in for the whole thing rather than
 * pushing a second, fake application into the accessibility tree.
 */

const NAV = [
  { label: "Dashboard", icon: LayoutDashboard, active: true },
  { label: "Series", icon: Layers },
  { label: "Data", icon: FileSpreadsheet },
  { label: "Reports", icon: FileBarChart2 },
  { label: "Connectors", icon: Database },
  { label: "LLM Usage", icon: Activity },
  { label: "Settings", icon: Settings },
] satisfies { label: string; icon: LucideIcon; active?: boolean }[];

const KPIS = [
  { icon: CreditCard, label: "Total forecast", value: "$4.82M", delta: "↗ 6.4%", tone: "positive", note: "vs last period" },
  { icon: Activity, label: "Actual to date", value: "$3.11M", delta: "↗ 2.9%", tone: "positive", note: "vs plan" },
  { icon: Target, label: "Accuracy", value: "91.4%", delta: "↗ 1.8pp", tone: "positive", note: "vs previous run" },
  { icon: Gauge, label: "Average error", value: "8.6%", delta: "↘ 0.4pp", tone: "positive", note: "across backtests" },
  { icon: TrendingUp, label: "Best case", value: "$5.24M", delta: "P90", tone: "neutral", note: "upper interval" },
  { icon: TrendingDown, label: "Worst case", value: "$4.31M", delta: "P10", tone: "neutral", note: "lower interval" },
] satisfies { icon: LucideIcon; label: string; value: string; delta: string; tone: string; note: string }[];

const CATEGORIES = [
  { label: "Beverages", share: "34%", colour: "var(--navy)", dash: "82 157", rotate: -90 },
  { label: "Frozen", share: "23%", colour: "var(--accent)", dash: "55 184", rotate: -6 },
  { label: "Household", share: "22%", colour: "var(--teal)", dash: "53 186", rotate: 76 },
  { label: "Personal care", share: "21%", colour: "var(--sand)", dash: "49 190", rotate: 155 },
];

const INSIGHTS = [
  {
    icon: AlertTriangle,
    tone: "warning",
    title: "Frozen is getting harder to call",
    body: "The range on Frozen has more than doubled since the last run. Three products went stop-start in June.",
    metric: "2.1× wider",
  },
  {
    icon: TrendingUp,
    tone: "positive",
    title: "Accuracy improved after the refit",
    body: "The error rate fell from 10.4% to 8.6% once a seasonal model took over as the ranked winner.",
    metric: "−1.8 pp",
  },
  {
    icon: Lightbulb,
    tone: "neutral",
    title: "Try a weekly view",
    body: "The season repeats once a year. Reporting daily is adding noise without adding signal.",
    metric: "Weekly",
  },
] satisfies { icon: LucideIcon; tone: string; title: string; body: string; metric: string }[];

const INSIGHT_TONES: Record<string, string> = {
  warning: "bg-warning-soft text-warning",
  positive: "bg-positive-soft text-positive",
  neutral: "bg-surface-muted text-text-secondary",
};

const CHIP =
  "inline-flex items-center gap-1.5 rounded-chip border border-border bg-surface px-2 py-1 text-caption text-text-secondary";

function delay(ms: number, key = "--reveal-delay"): CSSProperties {
  return { [key]: `${ms}ms` } as CSSProperties;
}

export function DashboardPreview() {
  return (
    <div>
      <div className="relative">
        <div className="scroll-thin overflow-x-auto overflow-y-hidden rounded-[14px] pb-0.5">
          <PreviewFrame />
        </div>

        {/* The frame is wider than any column it can sit in, so it always
            scrolls. Fade the cut edge and say so, rather than leaving it
            looking like a screenshot that got clipped. */}
        <div
          className="pointer-events-none absolute inset-y-0 right-0 w-20 rounded-r-[14px] bg-gradient-to-l from-canvas to-transparent"
          aria-hidden
        />
      </div>

      <p className="mt-3 font-mono text-caption text-text-muted">
        The dashboard at full width &mdash; scroll sideways for the rest.
      </p>
    </div>
  );
}

function PreviewFrame() {
  return (
    <Reveal
      amount={0.05}
      className={cn(
        "min-w-[1592px] overflow-hidden rounded-[14px] border border-border-strong bg-canvas",
        "shadow-[0_24px_60px_-30px_var(--overlay),0_2px_8px_rgba(25,23,19,.05)]",
      )}
      role="img"
      aria-label="The Forecast Hub dashboard: six headline figures, a forecast-versus-actual chart with its confidence band, a category split, and a rail of written insights."
    >
      <WindowChrome />
      <AppHeader />

      <div className="flex">
        <Sidebar />
        <Workspace />
        <InsightsRail />
      </div>
    </Reveal>
  );
}

function WindowChrome() {
  return (
    <div className="flex h-9 items-center gap-2 border-b border-border bg-surface-muted px-3.5">
      {[0, 1, 2].map((dot) => (
        <span key={dot} className="h-2 w-2 rounded-full bg-border-strong" aria-hidden />
      ))}
      <span className="ml-3 font-mono text-caption text-text-muted">localhost:3000</span>
    </div>
  );
}

function AppHeader() {
  return (
    <div className="flex h-header items-center gap-2.5 border-b border-border bg-surface px-5">
      <span className="flex h-8 w-8 items-center justify-center rounded-[9px] bg-accent" aria-hidden>
        <TrendingUp className="h-4 w-4 text-on-accent" />
      </span>
      <span className="text-title font-semibold tracking-[-0.01em] text-text-primary">
        Forecast Hub
      </span>
      <span className="ml-1 h-5 w-px bg-border" aria-hidden />
      <span className="text-meta font-medium text-text-secondary">Dashboard</span>

      <div className="ml-auto flex items-center gap-2">
        <span className={CHIP}>
          Run · 2026-08-04 <span className="text-text-muted">▾</span>
        </span>
        <span className={CHIP}>
          Base case <span className="text-text-muted">▾</span>
        </span>
        <span className={CHIP}>
          12 months <span className="text-text-muted">▾</span>
        </span>
        <span className="mx-0.5 h-5 w-px bg-border" aria-hidden />
        <span className="inline-flex items-center gap-1.5 text-caption text-text-secondary">
          <span
            className="h-1.5 w-1.5 rounded-full bg-positive motion-safe:animate-pulse-dot"
            aria-hidden
          />
          Live
        </span>
      </div>
    </div>
  );
}

function Sidebar() {
  return (
    <div className="w-rail shrink-0 border-r border-border bg-surface pb-3">
      <div className="flex h-11 items-end px-3 pb-1.5">
        <span className="eyebrow">Workspace</span>
      </div>
      <div className="space-y-0.5 px-3">
        {NAV.map((item) => (
          <span
            key={item.label}
            className={cn(
              "flex h-9 items-center gap-2.5 rounded-input px-2.5 text-meta font-medium",
              item.active ? "bg-accent-soft text-text-primary" : "text-text-secondary",
            )}
          >
            <item.icon
              className={cn("h-4 w-4 shrink-0", item.active ? "text-accent" : "text-text-muted")}
              aria-hidden
            />
            {item.label}
          </span>
        ))}
      </div>
    </div>
  );
}

function Workspace() {
  return (
    <div className="min-w-0 flex-1 bg-canvas px-6 py-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-heading font-semibold tracking-[-0.015em] text-text-primary">
            Overview
          </div>
          <div className="mt-0.5 text-meta text-text-secondary">
            Comprehensive view of your forecast performance
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex h-8 items-center rounded-input border border-border bg-surface px-3 text-meta font-medium text-text-primary">
            Upload Data
          </span>
          <span className="inline-flex h-8 items-center rounded-input border border-accent bg-accent px-3 text-meta font-medium text-on-accent">
            + New Forecast
          </span>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-6 gap-3">
        {KPIS.map((card, index) => (
          <Reveal
            key={card.label}
            delay={80 + index * 55}
            className="rounded-card border border-border bg-surface p-3 shadow-card"
          >
            <card.icon className="h-3.5 w-3.5 text-text-muted" aria-hidden />
            <div className="mt-2 text-caption text-text-secondary">{card.label}</div>
            <div className="mt-1 text-kpi font-semibold tracking-[-0.02em] text-text-primary num">
              {card.value}
            </div>
            <div className="mt-1.5">
              <span
                className={cn(
                  "inline-flex items-center rounded-chip border px-1.5 py-0.5 text-caption font-medium num",
                  card.tone === "positive"
                    ? "border-positive-border bg-positive-soft text-positive"
                    : "border-border bg-surface-muted text-text-secondary",
                )}
              >
                {card.delta}
              </span>
            </div>
            <div className="mt-1.5 text-caption text-text-muted">{card.note}</div>
          </Reveal>
        ))}
      </div>

      <div className="mt-3 grid grid-cols-[52fr_48fr] gap-3">
        <ForecastChart />
        <CategorySplit />
      </div>
    </div>
  );
}

function ForecastChart() {
  return (
    <div className="rounded-card border border-border bg-surface shadow-card">
      <div className="flex items-start justify-between gap-3 px-4 pb-3 pt-3.5">
        <div>
          <div className="panel-title">Forecast vs Actual</div>
          <div className="mt-0.5 text-caption text-text-muted">SARIMAX · 80% interval</div>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="rounded-chip border border-border bg-surface-muted px-2 py-1 text-caption font-medium text-text-primary">
            Recent
          </span>
          <span className="rounded-chip px-2 py-1 text-caption text-text-muted">Last year</span>
        </div>
      </div>

      <div className="px-4 pb-4">
        <svg
          viewBox="0 0 520 200"
          width="100%"
          height="200"
          preserveAspectRatio="none"
          className="block"
          aria-hidden
        >
          <g stroke="var(--border)" strokeWidth="1">
            {[20, 65, 110, 155, 182].map((y) => (
              <line key={y} x1="0" y1={y} x2="520" y2={y} />
            ))}
          </g>

          {/* Everything to the right of "today" wipes in as one gesture. */}
          <g className="wipe-x" style={delay(1150, "--wipe-delay")}>
            <path
              d="M300 96 L340 84 L380 70 L420 58 L460 46 L500 32 L500 96 L460 100 L420 104 L380 112 L340 118 L300 118 Z"
              fill="var(--accent)"
              opacity=".1"
            />
            <polyline
              points="300,96 340,101 380,91 420,81 460,73 500,64"
              fill="none"
              stroke="var(--accent)"
              strokeWidth="2"
              strokeDasharray="5 4"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </g>

          <polyline
            className="draw-line"
            style={{ "--draw-length": "320", "--draw-delay": "220ms" } as CSSProperties}
            points="10,150 50,138 90,144 130,124 170,132 210,110 250,112 300,96"
            fill="none"
            stroke="var(--navy)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          <line
            x1="300"
            y1="8"
            x2="300"
            y2="182"
            stroke="var(--border-strong)"
            strokeWidth="1"
            strokeDasharray="3 3"
          />
          <circle cx="300" cy="96" r="3.5" fill="var(--surface)" stroke="var(--navy)" strokeWidth="2" />
        </svg>

        <div className="mt-2 flex items-center gap-4">
          {[
            { label: "Actual", colour: "var(--navy)" },
            { label: "Forecast", colour: "var(--accent)" },
            { label: "Interval", colour: "var(--accent-border)" },
          ].map((key) => (
            <span
              key={key.label}
              className="inline-flex items-center gap-1.5 text-caption text-text-secondary"
            >
              <span
                className="h-2 w-3 rounded-[2px]"
                style={{ background: key.colour }}
                aria-hidden
              />
              {key.label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function CategorySplit() {
  return (
    <div className="rounded-card border border-border bg-surface shadow-card">
      <div className="px-4 pb-3 pt-3.5">
        <div className="panel-title">By category</div>
        <div className="mt-0.5 text-caption text-text-muted">Share of forecast value</div>
      </div>

      <div className="flex items-center gap-5 px-4 pb-4">
        <svg viewBox="0 0 100 100" width="128" height="128" className="shrink-0" aria-hidden>
          <g className="donut-spin">
            {CATEGORIES.map((slice, index) => (
              <circle
                key={slice.label}
                className="donut-in"
                style={delay(300 + index * 120, "--donut-delay")}
                cx="50"
                cy="50"
                r="38"
                fill="none"
                stroke={slice.colour}
                strokeWidth="15"
                strokeDasharray={slice.dash}
                transform={`rotate(${slice.rotate} 50 50)`}
              />
            ))}
          </g>
        </svg>

        <div className="min-w-0 flex-1 space-y-2">
          {CATEGORIES.map((slice, index) => (
            <Reveal
              key={slice.label}
              delay={360 + index * 90}
              className="flex items-center gap-2 text-caption text-text-secondary"
            >
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ background: slice.colour }}
                aria-hidden
              />
              <span className="truncate">{slice.label}</span>
              <span className="ml-auto font-medium text-text-primary num">{slice.share}</span>
            </Reveal>
          ))}
        </div>
      </div>
    </div>
  );
}

function InsightsRail() {
  return (
    <div className="w-insights shrink-0 border-l border-border bg-surface">
      <div className="px-4 pb-2 pt-4">
        <div className="flex items-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden />
          <span className="text-subhead font-semibold text-text-primary">Forecast Insights</span>
          <span className="ml-auto text-caption text-text-muted num">6</span>
        </div>
        <p className="mt-1 text-caption text-text-muted">Written by the platform.</p>
        <div className="sweep mt-2.5 h-px w-full bg-gradient-to-r from-accent-border to-transparent" />
      </div>

      <div className="space-y-2.5 px-3 pb-3">
        {INSIGHTS.map((insight, index) => (
          <Reveal
            key={insight.title}
            delay={200 + index * 120}
            className="rounded-card border border-border bg-surface p-3"
          >
            <div className="flex items-start gap-2">
              <span
                className={cn(
                  "mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-[6px]",
                  INSIGHT_TONES[insight.tone],
                )}
                aria-hidden
              >
                <insight.icon className="h-3 w-3" />
              </span>
              <span className="text-body font-semibold leading-[17px] text-text-primary">
                {insight.title}
              </span>
            </div>
            <p className="mt-1.5 text-caption leading-[16px] text-text-secondary">{insight.body}</p>
            <div className="mt-2.5 flex items-center justify-between gap-2">
              <span className="text-caption font-medium text-text-muted num">{insight.metric}</span>
              <span className="text-caption font-medium text-accent">View Details →</span>
            </div>
          </Reveal>
        ))}
      </div>
    </div>
  );
}
