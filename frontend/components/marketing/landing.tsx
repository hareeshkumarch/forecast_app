"use client";

import { BarChart3, CirclePlay, FileUp, Gauge, Layers3, Table2 } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { CheckDiagram } from "@/components/marketing/check-diagram";
import { CountUp } from "@/components/marketing/count-up";
import { DemandScape } from "@/components/marketing/demand-scape";
import { Arrow, FloatingNav } from "@/components/marketing/floating-nav";
import { Mark } from "@/components/marketing/mark";
import { PointerGlow } from "@/components/marketing/pointer-glow";
import { RangeVsLine } from "@/components/marketing/range-vs-line";
import { Reveal, useMotionReady } from "@/components/marketing/reveal";
import { SplitWords } from "@/components/marketing/split-words";
import { cn } from "@/lib/utils";

const SHELL = "page-shell";

const STEPS = [
  {
    icon: FileUp,
    title: "Bring in some data",
    body: "Drop in a spreadsheet of what you have sold. That is the only thing we need from you.",
    foot: "A spreadsheet is enough",
  },
  {
    icon: Table2,
    title: "Say what to forecast",
    body: "We work out which column holds the date and which holds the sales, and show you before running.",
    foot: "You confirm before anything runs",
  },
  {
    icon: CirclePlay,
    title: "Run it",
    body: "Your forecast appears, week by week, with a range around every number.",
    foot: "About a minute",
    active: true,
  },
];

/*
 * Four numbers the product can actually be held to, not four numbers that
 * sounded good. In order: the accuracy the section below reports, the size of
 * the candidate set in `ModelKind`, the run budget in `core/budget.py`, and
 * the one file step 1 asks for. `count` is off for the one that has nowhere
 * to count from — a number ticking from zero to one reads as a fault.
 */
const PROOF = [
  { value: 94, unit: "%", count: true, label: "Right on weeks it had never seen" },
  { value: 10, unit: "", count: true, label: "Models it picks between, every run" },
  { value: 60, unit: "s", count: true, label: "Budgeted for a run, start to finish" },
  { value: 1, unit: "", count: false, label: "Spreadsheet to begin. Nothing else" },
];

const FEATURES = [
  {
    icon: BarChart3,
    number: "01",
    title: "A forecast you can read",
    body: "See the number, its likely range, and the history behind it in one view.",
  },
  {
    icon: Layers3,
    number: "02",
    title: "Every level of the plan",
    body: "Move from the whole business to a product, region, or channel without losing the story.",
  },
  {
    icon: Gauge,
    number: "03",
    title: "Accuracy you can inspect",
    body: "The same test runs on your own past, so the score belongs to your data—not a benchmark.",
  },
];

export function Landing() {
  const motionReady = useMotionReady();

  return (
    <div className={cn("forecast-landing min-h-screen overflow-x-clip bg-canvas text-text-primary", motionReady && "motion-ready")}>
      <a href="#main-content" className="skip-link">Skip to content</a>
      <PointerGlow />
      <FloatingNav />
      <main id="main-content">
        <Hero />
        <HowItWorks />
        <Features />
        <Compare />
        <Accuracy />
        <Closing />
      </main>
      <Footer />
    </div>
  );
}

function Eyebrow({
  children,
  light = false,
  rule = true,
}: {
  children: ReactNode;
  light?: boolean;
  /** Off in the hero, where a pulsing status dot already sits to the left. */
  rule?: boolean;
}) {
  return (
    // inline-flex, not flex: the closing section centres its content with
    // `text-align`, which only moves an inline-level box.
    <div className={cn("inline-flex items-center gap-3 font-mono text-site-caption uppercase tracking-[0.22em]", light ? "text-land-invert-muted" : "text-land-dim")}>
      {rule ? (
        <span aria-hidden className={cn("eyebrow-rule h-px w-7 shrink-0", light ? "bg-land-invert-accent" : "bg-accent")} />
      ) : null}
      {children}
    </div>
  );
}

function Hero() {
  return (
    <section id="top" className="relative isolate overflow-hidden pb-[var(--section-gap)] pt-[calc(var(--nav-total)+clamp(2.5rem,5vw,4.5rem))]">
      <div className="hero-wash pointer-events-none absolute inset-x-0 top-[var(--nav-total)] -z-10 mx-auto h-[min(54rem,76vw)] max-h-[620px] min-h-[360px] max-w-[1200px]" aria-hidden />

      <div className="page-shell flex flex-col items-center text-center">
        <Reveal variant="fade" duration={420} className="flex items-center justify-center gap-3">
          <span className="status-dot size-2 bg-accent" aria-hidden />
          <Eyebrow rule={false}>Demand forecasting for planning teams</Eyebrow>
        </Reveal>

        <SplitWords
          as="h1"
          text="See your demand before it arrives."
          delay={70}
          stagger={78}
          className="mt-6 max-w-[17ch] text-balance font-display text-site-display font-normal sm:mt-7"
        />

        <Reveal as="p" delay={150} duration={620} className="mt-5 max-w-[58ch] text-site-lead text-text-secondary">
          Connect your sales history and see how much you will sell, week by week, with an honest
          range around every number.
        </Reveal>

        <Reveal delay={240} duration={620} className="mt-8 flex w-full flex-col items-stretch justify-center gap-3 min-[430px]:w-auto min-[430px]:flex-row min-[430px]:items-center">
          <Link
            href="/dashboard"
            className="cta-nudge group inline-flex h-[52px] items-center justify-center gap-3 border-2 border-land-cta bg-land-cta px-7 text-site-body font-medium text-land-cta-ink hover:border-accent hover:bg-land-cta-hover sm:h-[56px] sm:px-8"
          >
            Open the dashboard
            <Arrow />
          </Link>
          <Link
            href="#how-it-works"
            className="hero-secondary-link inline-flex h-[52px] items-center justify-center border border-border-strong bg-surface/75 px-6 text-site-body font-medium text-text-secondary backdrop-blur-sm hover:border-text-muted hover:bg-surface sm:h-[56px]"
          >
            See how it works
            <span className="ml-2" aria-hidden>↓</span>
          </Link>
        </Reveal>
      </div>

      <Reveal delay={330} variant="scale" duration={760} className="page-shell mt-10 sm:mt-12">
        <div className="hero-stage">
          <div className="mb-5 border-b border-land-rule-soft pb-4">
            <p className="font-mono text-site-caption uppercase tracking-[0.15em] text-land-dim">Interactive forecast preview</p>
          </div>
          <DemandScape />
        </div>
      </Reveal>

      <Proof />
    </section>
  );
}

/*
 * The band sits below the chart rather than above it. Everything in the hero
 * above this point is a claim; the chart is the demonstration, and these are
 * what the demonstration is worth. Putting it any higher would also push the
 * call to action off the fold, which `audits/track-a.mjs` checks at three
 * viewport heights.
 */
function Proof() {
  return (
    <div className="page-shell mt-12 sm:mt-14">
      <dl className="grid border-l border-t border-land-rule sm:grid-cols-2 xl:grid-cols-4">
        {PROOF.map((stat, index) => (
          <Reveal
            key={stat.label}
            delay={index * 70}
            duration={560}
            // Glow only, no lift: shared borders with the tile next door.
            className="card-edge border-b border-r border-land-rule bg-surface/70 p-6 sm:p-7"
          >
            <dt className="text-stat font-bold text-text-primary">
              {stat.count ? <CountUp value={stat.value} /> : stat.value}
              <span className="text-accent">{stat.unit}</span>
            </dt>
            <dd className="mt-2 max-w-[26ch] font-mono text-site-caption text-land-dim">
              {stat.label}
            </dd>
          </Reveal>
        ))}
      </dl>
    </div>
  );
}

function HowItWorks() {
  return (
    <section id="how-it-works" className="section-pad border-t border-border">
      <div className={cn(SHELL, "grid gap-10 xl:grid-cols-[minmax(0,0.5fr)_minmax(0,1fr)] xl:gap-12")}>
        <Reveal variant="from-left" duration={640}>
          <Eyebrow>01 — Getting started</Eyebrow>
          <SplitWords
            text="From a spreadsheet to a plan in three steps."
            className="mt-4 max-w-[22ch] text-balance font-display text-site-h2 font-normal"
          />
          <p className="mt-5 max-w-[36ch] text-site-lead text-text-secondary">Nothing to configure. Nothing to maintain.</p>
        </Reveal>

        <div className="grid gap-4 sm:grid-cols-2">
          {STEPS.map((step, index) => (
            <Reveal
              key={step.title}
              delay={index * 90}
              variant={step.active ? "scale" : "from-right"}
              duration={620}
              className={cn(
                // card-lift as well as card-edge: these three sit in a gapped
                // grid, so raising one does not pull on a shared border.
                "card-edge card-lift flex flex-col border bg-surface p-6 sm:p-7",
                step.active
                  ? "border-text-primary bg-surface-muted sm:col-span-2"
                  : "border-land-rule",
              )}
            >
              <div className="flex items-center justify-between">
                <span className={cn("step-badge flex size-10 items-center justify-center border text-site-body", step.active ? "border-land-cta bg-land-cta text-land-cta-ink" : "border-border-strong text-land-dim")}>
                  {index + 1}
                </span>
                <step.icon className="motion-icon size-5 text-land-dim" strokeWidth={1.8} aria-hidden />
              </div>
              <h3 className="mt-5 text-site-h3 font-bold">{step.title}</h3>
              <p className="mt-2 max-w-[42ch] text-site-body text-text-secondary">{step.body}</p>
              <p className="mt-auto pt-6 font-mono text-site-caption text-land-dim">{step.foot}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function Features() {
  return (
    <section id="features" className="section-pad border-t border-border">
      <div className={SHELL}>
        <Reveal variant="from-left" duration={640}>
          <Eyebrow>What you get</Eyebrow>
          <SplitWords
            text="Everything a planner needs, and nothing they do not."
            className="mt-4 max-w-[26ch] text-balance font-display text-site-h2 font-normal"
          />
        </Reveal>

        <div className="mt-10 grid border-l border-t border-land-rule sm:grid-cols-2 xl:grid-cols-3">
          {FEATURES.map((feature, index) => (
            <Reveal key={feature.title} delay={index * 100} variant="scale" duration={640} className="card-edge flex flex-col border-b border-r border-land-rule bg-surface/70 p-6 sm:p-8">
              <div className="flex items-center justify-between font-mono text-site-caption uppercase tracking-[0.16em] text-land-dim">
                {feature.number}
                <feature.icon className="motion-icon size-5" strokeWidth={1.6} aria-hidden />
              </div>
              <h3 className="mt-10 text-site-h3 font-bold">{feature.title}</h3>
              <p className="mt-2 max-w-[42ch] text-site-body text-text-secondary">{feature.body}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function Compare() {
  return (
    <section id="compare" className="section-pad border-t border-border">
      <div className={cn(SHELL, "grid gap-10 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1fr)] lg:gap-16")}>
        <Reveal variant="from-left" duration={680}>
          <Eyebrow>Built for a real decision</Eyebrow>
          <SplitWords
            text="A range tells you more than a perfect-looking line."
            className="mt-4 max-w-[24ch] text-balance font-display text-site-h2 font-normal"
          />
          <p className="mt-5 max-w-[46ch] text-site-lead text-text-secondary">
            Forecast Hub shows what is most likely, how far it could move, and what changed since the last run.
          </p>
          <p className="mt-7 font-mono text-site-caption uppercase tracking-[0.14em] text-land-dim">
            One answer, with the uncertainty left in
          </p>
        </Reveal>
        <Reveal delay={120} variant="from-right" duration={720}>
          <RangeVsLine />
        </Reveal>
      </div>
    </section>
  );
}

function Accuracy() {
  return (
    <section id="accuracy" className="section-pad bg-land-invert text-land-invert-ink">
      <div className={cn(SHELL, "grid gap-12 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1fr)] lg:gap-16")}>
        <Reveal variant="from-left" duration={680}>
          <Eyebrow light>Accuracy</Eyebrow>
          <h2 className="mt-4 max-w-[24ch] text-balance font-display text-site-h2 font-normal">
            Right about{" "}
            <span className="whitespace-nowrap text-land-invert-accent">
              <CountUp value={94} />%
            </span>{" "}
            of the sales it had never seen.
          </h2>
          <p className="mt-5 max-w-[52ch] text-site-lead text-land-invert-secondary">
            That figure comes from your own history, not a benchmark. You can see it for any product,
            any region, any week — and watch it change as your sales change.
          </p>
        </Reveal>

        <Reveal delay={140} variant="from-right" duration={720}>
          <CheckDiagram />
          <div className="mt-10 border border-land-invert-border">
            <div className="p-6 sm:p-7">
              <h3 className="text-site-h3 font-bold">It is measured, not claimed</h3>
              <p className="mt-3 max-w-[62ch] text-site-body text-land-invert-muted">
                Before you ever see a number, we hide part of your own sales history and check whether the forecast would have got it right.
              </p>
            </div>
            <div className="border-t border-land-invert-rule p-6 sm:p-7">
              <h3 className="text-site-h3 font-bold">It keeps being checked</h3>
              <p className="mt-3 max-w-[62ch] text-site-body text-land-invert-muted">Every new run adds another real result to the score.</p>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function Closing() {
  return (
    <section className="section-pad">
      <Reveal variant="scale" duration={700} className="page-shell max-w-[46ch] text-center">
        <Eyebrow>Start with the data you have</Eyebrow>
        <SplitWords
          text="See what is coming next."
          stagger={80}
          className="mt-4 text-balance font-display text-site-h2 font-normal"
        />
        <Link href="/dashboard" className="cta-nudge group mt-8 inline-flex h-[52px] w-full items-center justify-center gap-3 border-2 border-land-cta bg-land-cta px-7 text-site-body font-medium text-land-cta-ink hover:border-accent hover:bg-land-cta-hover min-[430px]:w-auto sm:h-[56px] sm:px-8">
          Open the dashboard
          <Arrow />
        </Link>
      </Reveal>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-land-rule bg-surface/75">
      <Reveal
        variant="fade"
        duration={520}
        className={cn(SHELL, "flex flex-col gap-6 py-8 sm:flex-row sm:items-center")}
      >
        <div className="flex items-center gap-3">
          <Mark size={28} />
          <span className="text-site-h3 font-bold">Forecast Hub</span>
        </div>
        <p className="text-site-body text-land-dim sm:ml-auto">Demand forecasting for planning teams.</p>
        <Link href="/dashboard" className="font-mono text-site-caption uppercase tracking-[0.11em] text-accent hover:text-accent-hover">Open dashboard →</Link>
      </Reveal>
    </footer>
  );
}
