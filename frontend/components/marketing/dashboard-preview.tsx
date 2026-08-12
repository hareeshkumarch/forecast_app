import {
  ArrowUpRight,
  CalendarDays,
  CheckCircle2,
  PackageCheck,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

import { Reveal } from "@/components/marketing/reveal";
import { cn } from "@/lib/utils";

const SCENARIOS = [
  { label: "Protected", value: "$4.71M", detail: "Downside floor" },
  { label: "Expected", value: "$5.08M", detail: "Current outlook", active: true },
  { label: "Stretch", value: "$5.42M", detail: "Upside case" },
];

const DECISIONS: {
  icon: LucideIcon;
  label: string;
  title: string;
  detail: string;
  tone: "positive" | "warning" | "accent";
}[] = [
  {
    icon: PackageCheck,
    label: "Act now",
    title: "Lift beverage stock",
    detail: "Demand is tracking 8.4% above plan.",
    tone: "positive",
  },
  {
    icon: TriangleAlert,
    label: "Watch",
    title: "Review frozen targets",
    detail: "The category is 1.8% below plan.",
    tone: "warning",
  },
  {
    icon: ShieldCheck,
    label: "Covered",
    title: "Holiday capacity",
    detail: "The expected peak stays within limits.",
    tone: "accent",
  },
];

export function DashboardPreview() {
  return (
    <Reveal
      amount={0.05}
      className={cn(
        "planning-preview relative w-full overflow-hidden rounded-[24px] border border-border-strong bg-surface",
        "shadow-[0_34px_90px_-46px_var(--overlay),0_2px_12px_rgba(25,23,19,.06)]",
      )}
      role="img"
      aria-label="A weekly planning brief showing a twelve-month revenue outlook, three scenarios, and a short queue of recommended business decisions."
    >
      <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-accent-soft opacity-70 blur-3xl" />
      <PreviewHeader />
      <PreviewWorkspace />
    </Reveal>
  );
}

function PreviewHeader() {
  return (
    <div className="relative border-b border-border bg-surface/90 px-4 sm:px-6">
      <div className="flex min-h-16 items-center gap-3 py-3 sm:min-h-[72px]">
        <span
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[11px] bg-navy shadow-card"
          aria-hidden
        >
          <Sparkles className="h-[17px] w-[17px] text-on-accent" />
        </span>
        <div className="min-w-0">
          <div className="truncate text-subhead font-semibold text-text-primary">
            Weekly planning brief
          </div>
          <div className="hidden text-caption text-text-muted sm:block">
            Northstar retail · 18 active series
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <span className="hidden items-center gap-1.5 rounded-chip border border-border bg-canvas px-2.5 py-1.5 text-caption text-text-secondary sm:inline-flex">
            <CalendarDays className="h-3.5 w-3.5 text-text-muted" aria-hidden />
            Aug 2026 · Jul 2027
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-chip border border-positive-border bg-positive-soft px-2.5 py-1.5 text-caption font-medium text-positive">
            <span className="h-1.5 w-1.5 rounded-full bg-positive" aria-hidden />
            Refreshed
          </span>
        </div>
      </div>
    </div>
  );
}

function PreviewWorkspace() {
  return (
    <div className="relative bg-canvas/80 p-3 sm:p-5 lg:p-6">
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.58fr)_minmax(280px,.72fr)]">
        <ForecastRunway />
        <DecisionQueue />
      </div>
      <ScenarioStrip />
    </div>
  );
}

function ForecastRunway() {
  return (
    <div className="min-w-0 overflow-hidden rounded-[16px] border border-border bg-surface shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border px-4 py-4 sm:px-5">
        <div>
          <div className="text-caption font-medium text-text-muted">Next 12 months</div>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-stat font-semibold text-text-primary num">
              $5.08M
            </span>
            <span className="inline-flex items-center gap-1 text-caption font-semibold text-positive">
              <TrendingUp className="h-3.5 w-3.5" aria-hidden />
              6.8% above plan
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3 text-caption text-text-secondary">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-4 rounded-full bg-navy" aria-hidden /> Actual
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-4 rounded-full bg-accent" aria-hidden /> Outlook
          </span>
        </div>
      </div>

      <div className="relative px-2 pb-2 pt-4 sm:px-4 sm:pb-4">
        <div className="pointer-events-none absolute right-[13%] top-[18%] z-10 hidden rounded-[10px] border border-accent-border bg-surface px-3 py-2 shadow-popover sm:block">
          <div className="text-micro font-semibold uppercase tracking-[0.06em] text-accent">
            Holiday peak
          </div>
          <div className="mt-0.5 text-caption font-medium text-text-primary">Capacity looks healthy</div>
        </div>

        <svg viewBox="0 0 820 310" className="block h-auto w-full" aria-hidden>
          <defs>
            <linearGradient id="brief-range" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity=".2" />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity=".025" />
            </linearGradient>
            <linearGradient id="brief-area" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--navy)" stopOpacity=".11" />
              <stop offset="100%" stopColor="var(--navy)" stopOpacity="0" />
            </linearGradient>
          </defs>

          <g stroke="var(--border)" strokeWidth="1">
            {[26, 86, 146, 206, 266].map((y) => (
              <line key={y} x1="18" y1={y} x2="802" y2={y} />
            ))}
          </g>

          <path
            d="M18 236 C66 219 111 229 154 203 S235 184 280 190 S357 139 410 151 L410 266 L18 266 Z"
            fill="url(#brief-area)"
          />
          <path
            d="M410 126 C472 104 523 96 573 73 C633 46 704 45 802 31 L802 212 C724 204 653 218 578 226 C517 232 466 207 410 190 Z"
            fill="url(#brief-range)"
          />
          <path
            d="M18 236 C66 219 111 229 154 203 S235 184 280 190 S357 139 410 151"
            fill="none"
            stroke="var(--navy)"
            strokeLinecap="round"
            strokeWidth="4"
          />
          <path
            d="M410 151 C468 139 520 125 573 104 C635 80 705 75 802 55"
            fill="none"
            stroke="var(--accent)"
            strokeDasharray="9 8"
            strokeLinecap="round"
            strokeWidth="4"
          />
          <line
            x1="410"
            y1="18"
            x2="410"
            y2="266"
            stroke="var(--border-strong)"
            strokeDasharray="4 6"
          />
          <circle cx="410" cy="151" r="6" fill="var(--surface)" stroke="var(--navy)" strokeWidth="4" />
          <circle cx="703" cy="75" r="5" fill="var(--surface)" stroke="var(--accent)" strokeWidth="3" />

          <g fill="var(--text-muted)" fontSize="11" fontFamily="var(--font-plex-mono)">
            <text x="18" y="298">FEB</text>
            <text x="206" y="298">MAY</text>
            <text x="395" y="298">AUG</text>
            <text x="590" y="298">NOV</text>
            <text x="774" y="298">FEB</text>
          </g>
        </svg>
      </div>
    </div>
  );
}

function DecisionQueue() {
  return (
    <div className="rounded-[16px] border border-border bg-surface p-4 shadow-card sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-subhead font-semibold text-text-primary">Decision queue</div>
          <div className="mt-0.5 text-caption text-text-muted">What needs attention this week</div>
        </div>
        <span className="flex h-8 w-8 items-center justify-center rounded-[9px] bg-accent-soft text-accent">
          <CheckCircle2 className="h-4 w-4" aria-hidden />
        </span>
      </div>

      <div className="mt-4 divide-y divide-border">
        {DECISIONS.map((item) => (
          <div key={item.title} className="flex gap-3 py-3.5 first:pt-1 last:pb-1">
            <span
              className={cn(
                "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px]",
                item.tone === "positive" && "bg-positive-soft text-positive",
                item.tone === "warning" && "bg-warning-soft text-warning",
                item.tone === "accent" && "bg-accent-soft text-accent",
              )}
            >
              <item.icon className="h-4 w-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <div
                className={cn(
                  "text-micro font-semibold uppercase tracking-[0.06em]",
                  item.tone === "positive" && "text-positive",
                  item.tone === "warning" && "text-warning",
                  item.tone === "accent" && "text-accent",
                )}
              >
                {item.label}
              </div>
              <div className="mt-0.5 text-subhead font-semibold text-text-primary">{item.title}</div>
              <div className="mt-0.5 text-caption text-text-secondary">{item.detail}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 flex items-center gap-2 rounded-[10px] border border-accent-border bg-accent-soft px-3 py-2.5 text-caption font-semibold text-accent">
        Open the full brief
        <ArrowUpRight className="ml-auto h-3.5 w-3.5" aria-hidden />
      </div>
    </div>
  );
}

function ScenarioStrip() {
  return (
    <div className="mt-3 grid gap-2 rounded-[16px] border border-border bg-surface p-2 shadow-card sm:grid-cols-3">
      {SCENARIOS.map((scenario) => (
        <div
          key={scenario.label}
          className={cn(
            "flex items-center gap-3 rounded-[11px] px-3 py-3 sm:block sm:px-4",
            scenario.active ? "border border-accent-border bg-accent-soft" : "border border-transparent",
          )}
        >
          <div className="min-w-[72px] text-caption font-medium text-text-secondary">{scenario.label}</div>
          <div className="text-title font-semibold tracking-[-0.02em] text-text-primary num sm:mt-1">
            {scenario.value}
          </div>
          <div className="ml-auto text-caption text-text-muted sm:ml-0 sm:mt-0.5">{scenario.detail}</div>
        </div>
      ))}
    </div>
  );
}
