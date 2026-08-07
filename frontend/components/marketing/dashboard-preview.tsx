import {
  Activity,
  ArrowUpRight,
  CalendarDays,
  CheckCircle2,
  CircleDollarSign,
  Gauge,
  Layers3,
  Sparkles,
  Target,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import type { CSSProperties } from "react";

import { Reveal } from "@/components/marketing/reveal";
import { cn } from "@/lib/utils";

/*
 * A responsive product vignette for the landing page. It deliberately shows
 * a planning view rather than duplicating the real dashboard screen below
 * /dashboard, so visitors see another useful side of the product.
 */

const SUMMARY = [
  {
    icon: CircleDollarSign,
    label: "Expected revenue",
    value: "$5.08M",
    delta: "+6.8%",
    detail: "against current plan",
  },
  {
    icon: Target,
    label: "Forecast accuracy",
    value: "92.6%",
    delta: "+2.1pp",
    detail: "after the latest refit",
  },
  {
    icon: Gauge,
    label: "Risk-adjusted",
    value: "$4.71M",
    delta: "P50",
    detail: "most likely outcome",
  },
] satisfies {
  icon: LucideIcon;
  label: string;
  value: string;
  delta: string;
  detail: string;
}[];

const DRIVERS = [
  { label: "Beverages", value: "$1.72M", change: "+8.4%", width: "88%" },
  { label: "Household", value: "$1.26M", change: "+3.1%", width: "66%" },
  { label: "Frozen", value: "$1.04M", change: "−1.8%", width: "52%", caution: true },
];

function delay(ms: number, key = "--reveal-delay"): CSSProperties {
  return { [key]: `${ms}ms` } as CSSProperties;
}

export function DashboardPreview() {
  return (
    <Reveal
      amount={0.05}
      className={cn(
        "w-full overflow-hidden rounded-[18px] border border-border-strong bg-surface",
        "shadow-[0_30px_80px_-42px_var(--overlay),0_2px_10px_rgba(25,23,19,.05)]",
      )}
      role="img"
      aria-label="Forecast Hub planning workspace showing expected revenue, forecast accuracy, a twelve-month outlook, key category drivers, and a written forecast insight."
    >
      <PreviewHeader />
      <PreviewWorkspace />
    </Reveal>
  );
}

function PreviewHeader() {
  return (
    <div className="border-b border-border bg-surface px-4 sm:px-5">
      <div className="flex h-14 items-center gap-3 sm:h-[68px]">
        <span
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] bg-accent"
          aria-hidden
        >
          <TrendingUp className="h-4 w-4 text-on-accent" />
        </span>
        <div className="min-w-0">
          <div className="truncate text-subhead font-semibold text-text-primary">Northstar plan</div>
          <div className="hidden text-caption text-text-muted sm:block">Retail portfolio · FY 2026</div>
        </div>

        <div className="ml-3 hidden h-7 w-px bg-border md:block" aria-hidden />
        <div className="hidden items-center gap-1 md:flex">
          <span className="rounded-chip bg-accent-soft px-3 py-1.5 text-caption font-semibold text-accent">
            Summary
          </span>
          <span className="px-3 py-1.5 text-caption font-medium text-text-secondary">Forecast</span>
          <span className="px-3 py-1.5 text-caption font-medium text-text-secondary">Scenarios</span>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <span className="hidden items-center gap-1.5 rounded-chip border border-border bg-canvas px-2.5 py-1.5 text-caption text-text-secondary sm:inline-flex">
            <CalendarDays className="h-3.5 w-3.5 text-text-muted" aria-hidden />
            Aug 2026 · Jul 2027
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-chip border border-positive-border bg-positive-soft px-2.5 py-1.5 text-caption font-medium text-positive">
            <span className="h-1.5 w-1.5 rounded-full bg-positive" aria-hidden />
            Updated
          </span>
        </div>
      </div>
    </div>
  );
}

function PreviewWorkspace() {
  return (
    <div className="bg-canvas p-3 sm:p-5 lg:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-meta font-medium text-text-muted">Portfolio outlook</div>
          <div className="mt-1 text-heading font-semibold tracking-[-0.015em] text-text-primary sm:text-kpi">
            Your next 12 months, at a glance
          </div>
        </div>
        <span className="inline-flex items-center gap-1.5 text-caption font-medium text-positive">
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
          18 series successfully refreshed
        </span>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        {SUMMARY.map((item, index) => (
          <Reveal
            key={item.label}
            delay={80 + index * 70}
            className="rounded-card border border-border bg-surface p-4 shadow-card"
          >
            <div className="flex items-center justify-between gap-3">
              <span className="flex h-8 w-8 items-center justify-center rounded-[9px] bg-surface-muted">
                <item.icon className="h-4 w-4 text-text-muted" aria-hidden />
              </span>
              <span
                className={cn(
                  "rounded-chip border px-2 py-1 text-caption font-semibold num",
                  item.delta.startsWith("+")
                    ? "border-positive-border bg-positive-soft text-positive"
                    : "border-border bg-surface-muted text-text-secondary",
                )}
              >
                {item.delta}
              </span>
            </div>
            <div className="mt-4 text-caption text-text-secondary">{item.label}</div>
            <div className="mt-1 text-kpi font-semibold tracking-[-0.025em] text-text-primary num sm:text-[28px]">
              {item.value}
            </div>
            <div className="mt-1 text-caption text-text-muted">{item.detail}</div>
          </Reveal>
        ))}
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1.65fr)_minmax(280px,.75fr)]">
        <OutlookChart />
        <Drivers />
      </div>

      <InsightBar />
    </div>
  );
}

function OutlookChart() {
  return (
    <div className="min-w-0 rounded-card border border-border bg-surface p-4 shadow-card sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="panel-title">Revenue outlook</div>
          <div className="mt-0.5 text-caption text-text-muted">Actuals through July · 80% range</div>
        </div>
        <div className="flex items-center gap-3 text-caption text-text-secondary">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-3 rounded-sm bg-navy" aria-hidden /> Actual
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-3 rounded-sm bg-accent" aria-hidden /> Forecast
          </span>
        </div>
      </div>

      <div className="mt-4 min-h-[190px] sm:min-h-[230px]">
        <svg viewBox="0 0 760 250" width="100%" height="100%" className="block" aria-hidden>
          <g stroke="var(--border)" strokeWidth="1">
            {[24, 82, 140, 198, 224].map((y) => (
              <line key={y} x1="8" y1={y} x2="752" y2={y} />
            ))}
          </g>

          <g className="wipe-x" style={delay(950, "--wipe-delay")}>
            <defs>
              <linearGradient id="preview-band" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--accent)" stopOpacity=".22" />
                <stop offset="100%" stopColor="var(--accent)" stopOpacity=".035" />
              </linearGradient>
            </defs>
            <path
              d="M380 102 C450 86 520 62 590 52 C652 42 700 30 744 20 L744 154 C690 150 636 157 584 166 C518 177 452 166 380 154 Z"
              fill="url(#preview-band)"
            />
            <path
              d="M380 117 C444 107 506 91 568 80 C626 70 687 57 744 43"
              fill="none"
              stroke="var(--accent)"
              strokeWidth="3"
              strokeDasharray="8 7"
              strokeLinecap="round"
            />
          </g>

          <path
            className="draw-line"
            style={{ "--draw-length": "520", "--draw-delay": "180ms" } as CSSProperties}
            d="M16 194 C54 178 88 184 126 166 S198 144 232 153 S298 119 334 126 S362 121 380 117"
            fill="none"
            stroke="var(--navy)"
            strokeWidth="3"
            strokeLinecap="round"
          />
          <line
            x1="380"
            y1="18"
            x2="380"
            y2="224"
            stroke="var(--border-strong)"
            strokeDasharray="4 5"
          />
          <circle cx="380" cy="117" r="5" fill="var(--surface)" stroke="var(--navy)" strokeWidth="3" />
          <g fill="var(--text-muted)" fontSize="11" fontFamily="var(--font-plex-mono)">
            <text x="16" y="245">FEB</text>
            <text x="188" y="245">MAY</text>
            <text x="368" y="245">AUG</text>
            <text x="548" y="245">NOV</text>
            <text x="720" y="245">FEB</text>
          </g>
        </svg>
      </div>
    </div>
  );
}

function Drivers() {
  return (
    <div className="rounded-card border border-border bg-surface p-4 shadow-card sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="panel-title">Category drivers</div>
          <div className="mt-0.5 text-caption text-text-muted">Contribution to the plan</div>
        </div>
        <Layers3 className="h-4 w-4 text-text-muted" aria-hidden />
      </div>

      <div className="mt-5 space-y-5">
        {DRIVERS.map((driver, index) => (
          <Reveal key={driver.label} delay={260 + index * 90}>
            <div className="flex items-center gap-3 text-caption">
              <span className="font-medium text-text-primary">{driver.label}</span>
              <span className="ml-auto text-text-secondary num">{driver.value}</span>
              <span className={cn("w-11 text-right font-medium num", driver.caution ? "text-warning" : "text-positive")}>
                {driver.change}
              </span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-muted">
              <div
                className={cn("h-full rounded-full", driver.caution ? "bg-gold" : "bg-accent")}
                style={{ width: driver.width }}
              />
            </div>
          </Reveal>
        ))}
      </div>

      <div className="mt-6 rounded-[10px] border border-border bg-canvas p-3">
        <div className="flex items-center gap-2 text-caption font-medium text-text-primary">
          <Activity className="h-3.5 w-3.5 text-accent" aria-hidden />
          Model health
          <span className="ml-auto text-positive">Strong</span>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-muted">
          <div className="h-full w-[92%] rounded-full bg-positive" />
        </div>
      </div>
    </div>
  );
}

function InsightBar() {
  return (
    <Reveal
      delay={420}
      className="mt-3 flex flex-col gap-3 rounded-card border border-accent-border bg-accent-soft p-4 sm:flex-row sm:items-center"
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-surface text-accent shadow-card">
        <Sparkles className="h-4 w-4" aria-hidden />
      </span>
      <div className="min-w-0">
        <div className="text-caption font-semibold uppercase tracking-[0.05em] text-accent">What changed</div>
        <p className="mt-0.5 text-subhead leading-[1.5] text-text-primary">
          Beverages now accounts for 41% of the upside, while Frozen is the only category trending below plan.
        </p>
      </div>
      <span className="inline-flex shrink-0 items-center gap-1 text-caption font-semibold text-accent sm:ml-auto">
        Review insight <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
      </span>
    </Reveal>
  );
}
