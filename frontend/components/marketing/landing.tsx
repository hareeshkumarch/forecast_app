"use client";

import {
  CheckCircle2,
  ShieldCheck,
  Sparkles,
  Target,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { CountUp } from "@/components/marketing/count-up";
import { DemandScape } from "@/components/marketing/demand-scape";
import { Arrow, FloatingNav } from "@/components/marketing/floating-nav";
import { Mark } from "@/components/marketing/mark";
import { PointerGlow } from "@/components/marketing/pointer-glow";
import { Reveal, useMotionReady } from "@/components/marketing/reveal";
import { ScrollProgress } from "@/components/marketing/scroll-progress";
import { RangeVsLine } from "@/components/marketing/range-vs-line";
import { SplitWords } from "@/components/marketing/split-words";
import { cn } from "@/lib/utils";

const SHELL = "page-shell";

const STEPS = [
  {
    title: "Bring in some data",
    body: "Drop in a spreadsheet of what you have sold. That is the only thing we need from you.",
    foot: "A spreadsheet is enough",
  },
  {
    title: "Say what to forecast",
    body: "We work out which column holds the date and which holds the sales, and show you before running.",
    foot: "You confirm before anything runs",
  },
  {
    title: "Run it",
    body: "Your forecast appears, week by week, with a range around every number.",
    foot: "About a minute",
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

/*
 * Each of these is a sentence, not a tile. They used to be three bordered
 * boxes with a number and a small icon in the corner — the arrangement every
 * product page uses, which is why it reads as furniture rather than as
 * something worth stopping on. Set large, on their own line, they are read.
 */
const FEATURES = [
  {
    lede: "A forecast you can read.",
    body: "The number, its likely range, and the history behind it — in one view, without a manual.",
  },
  {
    lede: "Every level of the plan.",
    body: "Move from the whole business down to a product, a region, or a channel without losing the story.",
  },
  {
    lede: "Accuracy you can inspect.",
    body: "The same test runs against your own past, so the score belongs to your data and not to a benchmark.",
  },
];

export function Landing() {
  const motionReady = useMotionReady();

  return (
    <div className={cn("forecast-landing min-h-screen overflow-x-clip bg-canvas text-text-primary", motionReady && "motion-ready")}>
      <a href="#main-content" className="skip-link">Skip to content</a>
      <ScrollProgress />
      <PointerGlow />
      <FloatingNav />
      <main id="main-content">
        <Hero />
        <HowItWorks />
        <Features />
        <InsightsPreview />
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
            href="/signin"
            className="cta-nudge group inline-flex h-[52px] items-center justify-center gap-3 border-2 border-land-cta bg-land-cta px-7 text-site-body font-medium text-land-cta-ink hover:border-accent hover:bg-land-cta-hover sm:h-[56px] sm:px-8"
          >
            Start forecasting
            <Arrow />
          </Link>
          <Link
            href="/dashboard"
            aria-label="Open the dashboard"
            className="hero-secondary-link inline-flex h-[52px] items-center justify-center border border-border-strong bg-surface/75 px-6 text-site-body font-medium text-text-secondary backdrop-blur-sm hover:border-text-muted hover:bg-surface sm:h-[56px]"
          >
            Explore the live workspace
          </Link>
        </Reveal>
        <Reveal delay={300} duration={520} className="mt-4 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 font-mono text-site-caption text-[#646b65]">
          <span className="inline-flex items-center gap-1.5"><CheckCircle2 className="size-3.5 text-[#287b59]" aria-hidden /> No setup project</span>
          <span className="inline-flex items-center gap-1.5"><ShieldCheck className="size-3.5 text-[#287b59]" aria-hidden /> Figures stay traceable</span>
          <Link href="#how-it-works" className="text-[#287b59] hover:text-[#175a3e]">See how it works ↓</Link>
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
    <div className="page-shell mt-14 sm:mt-16">
      <dl className="proof-band border-t border-land-rule">
        {PROOF.map((stat, index) => (
          <Reveal key={stat.label} delay={index * 90} duration={620} className="proof-figure">
            <dt className="font-display text-proof font-normal leading-[0.9] tracking-[-0.02em] text-text-primary">
              {stat.count ? <CountUp value={stat.value} /> : stat.value}
              <span className="text-accent">{stat.unit}</span>
            </dt>
            <dd className="proof-label mt-3 max-w-[22ch] text-site-body text-text-secondary">
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
      <div className={SHELL}>
        <Reveal variant="from-left" duration={640}>
          <Eyebrow>01 — Getting started</Eyebrow>
          <SplitWords
            text="From a spreadsheet to a plan in three steps."
            className="mt-4 max-w-[22ch] text-balance font-display text-site-h2 font-normal"
          />
          <p className="mt-5 max-w-[42ch] text-site-lead text-text-secondary">
            Nothing to configure. Nothing to maintain.
          </p>
        </Reveal>

        {/* The rule is the animation. It draws itself down the page as the
            section arrives, and each step fades in as the line reaches it —
            so the sequence is shown by the movement rather than stated by
            three numbered boxes. */}
        <ol className="step-rail mt-14 sm:mt-16">
          {STEPS.map((step, index) => (
            <Reveal
              key={step.title}
              as="li"
              delay={index * 150}
              duration={700}
              variant="from-left"
              className="step-row"
            >
              <span aria-hidden className="step-ordinal font-mono text-site-caption text-land-dim">
                {String(index + 1).padStart(2, "0")}
              </span>
              <div className="step-body">
                <h3 className="font-display text-site-h3-display font-normal text-text-primary">
                  {step.title}
                </h3>
                <p className="mt-3 max-w-[52ch] text-site-lead text-text-secondary">{step.body}</p>
                <p className="mt-4 font-mono text-site-caption uppercase tracking-[0.14em] text-land-dim">
                  {step.foot}
                </p>
              </div>
            </Reveal>
          ))}
        </ol>
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
        </Reveal>

        <div className="mt-10 sm:mt-12">
          {FEATURES.map((feature, index) => (
            <Reveal
              key={feature.lede}
              delay={index * 140}
              duration={720}
              variant="from-left"
              className="feature-line py-10 sm:py-12"
            >
              <div className="grid gap-4 lg:grid-cols-[auto_minmax(0,1fr)_minmax(0,0.85fr)] lg:gap-x-10 lg:gap-y-4">
                <span
                  aria-hidden
                  className="feature-ordinal font-mono text-site-caption tracking-[0.22em] text-land-dim"
                >
                  {String(index + 1).padStart(2, "0")}
                </span>
                <h3 className="text-balance font-display text-site-h2 font-normal leading-[1.05] text-text-primary">
                  {feature.lede}
                </h3>
                <p className="max-w-[46ch] self-end text-site-lead text-text-secondary">
                  {feature.body}
                </p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function InsightsPreview() {
  return (
    <section id="insights" className="section-pad border-t border-[#d8ddd7] bg-[#e8ebe6]">
      <div className={cn(SHELL, "grid items-start gap-10 lg:grid-cols-[minmax(0,0.72fr)_minmax(0,1fr)] lg:gap-16")}>
        <Reveal variant="from-left" duration={680}>
          <Eyebrow>Decision brief</Eyebrow>
          <h2 className="mt-4 max-w-[22ch] text-balance font-display text-site-h2 font-normal">
            Know what changed, why it matters, and what to do next.
          </h2>
          <p className="mt-5 max-w-[46ch] text-site-lead text-[#444b45]">
            Forecast Hub ranks the signals that deserve attention and keeps every conclusion tied to the computed evidence behind it.
          </p>
          <div className="mt-7 grid gap-3 text-site-body text-[#444b45] sm:grid-cols-2 lg:grid-cols-1">
            <p className="flex gap-3"><Target className="mt-1 size-4 shrink-0 text-[#287b59]" aria-hidden /><span><strong className="text-[#111512]">Prioritised.</strong> Risks and opportunities appear in decision order.</span></p>
            <p className="flex gap-3"><ShieldCheck className="mt-1 size-4 shrink-0 text-[#287b59]" aria-hidden /><span><strong className="text-[#111512]">Grounded.</strong> AI may refine the wording; it never invents the figures.</span></p>
          </div>
        </Reveal>

        <Reveal delay={120} variant="from-right" duration={720}>
          <div className="border border-[#bdc5bd] bg-[#fafbf9] shadow-[0_28px_70px_-52px_rgba(17,22,18,.7)]">
            <div className="flex items-center justify-between gap-4 border-b border-[#d8ddd7] px-5 py-4 sm:px-6">
              <div>
                <p className="font-mono text-[0.68rem] uppercase tracking-[0.16em] text-[#6a716b]">Decision brief · this run</p>
                <p className="mt-1 text-site-h3 font-bold">Three signals need attention</p>
              </div>
              <Sparkles className="size-5 text-[#287b59]" strokeWidth={1.7} aria-hidden />
            </div>

            <div className="grid gap-px bg-[#d8ddd7] sm:grid-cols-3">
              <div className="bg-[#fafbf9] p-5 sm:p-6">
                <p className="font-mono text-[0.68rem] uppercase tracking-[0.14em] text-[#8a6a31]">What changed</p>
                <p className="mt-4 text-site-h3 font-bold">West demand is softening</p>
                <p className="mt-2 text-site-body text-[#525953]">The next six weeks sit 8.4% below the recent baseline.</p>
              </div>
              <div className="bg-[#fafbf9] p-5 sm:p-6">
                <p className="font-mono text-[0.68rem] uppercase tracking-[0.14em] text-[#59605a]">Why it matters</p>
                <p className="mt-4 text-site-h3 font-bold">Inventory may run long</p>
                <p className="mt-2 text-site-body text-[#525953]">The downside falls outside the normal planning range.</p>
              </div>
              <div className="bg-[#eef4f0] p-5 sm:p-6">
                <p className="font-mono text-[0.68rem] uppercase tracking-[0.14em] text-[#287b59]">Next move</p>
                <p className="mt-4 text-site-h3 font-bold">Review the West order</p>
                <p className="mt-2 text-site-body text-[#425047]">Model a lower-receipts scenario before the buying cutoff.</p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-[#d8ddd7] px-5 py-3 font-mono text-[0.68rem] text-[#697069] sm:px-6">
              <span>Computed from 5 backtest folds</span>
              <span className="inline-flex items-center gap-1.5 text-[#287b59]"><span className="size-1.5 bg-[#287b59]" aria-hidden /> Figures verified</span>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function Compare() {
  return (
    <section id="compare" className="section-pad border-t border-[#d8ddd7]">
      <div className={cn(SHELL, "grid gap-10 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1fr)] lg:gap-16")}>
        <Reveal variant="from-left" duration={680}>
          <Eyebrow>Built for a real decision</Eyebrow>
          <h2 className="mt-4 max-w-[24ch] text-balance font-display text-site-h2 font-normal">
            A range tells you more than a perfect-looking line.
          </h2>
          <p className="mt-5 max-w-[46ch] text-site-lead text-[#3f463f]">
            Forecast Hub shows what is most likely, how far it could move, and what changed since the last run.
          </p>
          <p className="mt-7 font-mono text-site-caption uppercase tracking-[0.14em] text-[#747b74]">
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
      <div className={cn(SHELL, "max-w-[62rem]")}>
        <Reveal variant="fade" duration={680}>
          <Eyebrow light>Accuracy</Eyebrow>
        </Reveal>

        <Reveal delay={80} duration={760} className="mt-6">
          <p className="font-display text-accuracy font-normal leading-[0.86] tracking-[-0.03em] text-land-invert-accent">
            <CountUp value={94} />%
          </p>
        </Reveal>

        <Reveal delay={200} duration={720}>
          <h2 className="mt-6 max-w-[20ch] text-balance font-display text-site-h2 font-normal">
            of the sales it had never seen.
          </h2>
        </Reveal>

        <div className="mt-12 grid gap-10 border-t border-land-invert-rule pt-10 sm:grid-cols-2 sm:gap-14">
          <Reveal delay={280} duration={700}>
            <p className="max-w-[46ch] text-site-lead text-land-invert-secondary">
              That figure comes from your own history, not a benchmark — we hide part of your past
              and check whether the forecast would have got it right.
            </p>
          </Reveal>
          <Reveal delay={380} duration={700}>
            <p className="max-w-[46ch] text-site-lead text-land-invert-secondary">
              And it keeps being checked. Every run adds another real result to the score, for any
              product, any region, any week.
            </p>
          </Reveal>
        </div>
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
        <Link href="/signin" className="cta-nudge group mt-8 inline-flex h-[52px] w-full items-center justify-center gap-3 border-2 border-land-cta bg-land-cta px-7 text-site-body font-medium text-land-cta-ink hover:border-accent hover:bg-land-cta-hover min-[430px]:w-auto sm:h-[56px] sm:px-8">
          Start forecasting
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
        <div className="flex items-center gap-5">
          <Link href="/signin" className="font-mono text-site-caption uppercase tracking-[0.11em] text-accent hover:text-accent-hover">Sign in</Link>
          <Link href="/dashboard" className="font-mono text-site-caption uppercase tracking-[0.11em] text-accent hover:text-accent-hover">Live workspace →</Link>
        </div>
      </Reveal>
    </footer>
  );
}
