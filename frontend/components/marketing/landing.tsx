"use client";

import { CheckCircle2, ShieldCheck, Sparkles, Target } from "lucide-react";
import Link from "next/link";
import type { CSSProperties, ElementType, ReactNode } from "react";
import { useRef } from "react";

import { Atmosphere } from "@/components/marketing/atmosphere";
import { BuildStage } from "@/components/marketing/build-stage";
import { CinematicField } from "@/components/marketing/cinematic-field";
import { CountUp } from "@/components/marketing/count-up";
import { PrimaryCta, SecondaryCta } from "@/components/marketing/cta";
import { DemandScape } from "@/components/marketing/demand-scape";
import { FloatingNav } from "@/components/marketing/floating-nav";
import { Mark } from "@/components/marketing/mark";
import { ParallaxField } from "@/components/marketing/parallax";
import { Reveal, useMotionReady } from "@/components/marketing/reveal";
import { ScrollStage } from "@/components/marketing/scroll-stage";
import { ScrollDepth } from "@/components/marketing/scroll-depth";
import { RangeVsLine } from "@/components/marketing/range-vs-line";
import { SplitWords } from "@/components/marketing/split-words";
import { useTilt } from "@/components/marketing/tilt";
import { cn } from "@/lib/utils";

const SHELL = "page-shell";

const STEPS = [
  {
    title: "Drop in a spreadsheet",
    body: "Whatever your sales history already lives in.",
    foot: "Nothing to set up",
  },
  {
    title: "We find the columns",
    body: "The date and the quantity, shown back to you before anything runs.",
    foot: "You confirm first",
  },
  {
    title: "The forecast draws itself",
    body: "Week by week, with the range it could move inside.",
    foot: "About a minute",
  },
];

const PROOF = [
  {
    value: 94,
    unit: "%",
    count: true,
    label: "Right on weeks it had never seen",
  },
  {
    value: 10,
    unit: "",
    count: true,
    label: "Models it picks between, every run",
  },
  {
    value: 60,
    unit: "s",
    count: true,
    label: "Budgeted for a run, start to finish",
  },
  {
    value: 1,
    unit: "",
    count: false,
    label: "Spreadsheet to begin. Nothing else",
  },
];

const FEATURES = [
  {
    lede: "A forecast you can read.",
    body: "The number, its range and the history behind it, in one view.",
  },
  {
    lede: "Every level of the plan.",
    body: "The whole business, or one product, region or channel.",
  },
  {
    lede: "Accuracy you can inspect.",
    body: "Scored against your own past, never against a benchmark.",
  },
];

const SIGNALS = [
  {
    label: "What changed",
    title: "West demand is softening",
    body: "The next six weeks sit 8.4% below the recent baseline.",
    tone: "warn",
  },
  {
    label: "Why it matters",
    title: "Inventory may run long",
    body: "The downside falls outside the normal planning range.",
    tone: "neutral",
  },
  {
    label: "Next move",
    title: "Review the West order",
    body: "Model a lower-receipts scenario before the buying cutoff.",
    tone: "act",
  },
] as const;

export function Landing() {
  const motionReady = useMotionReady();

  return (
    <div
      className={cn(
        "forecast-landing min-h-screen overflow-x-clip bg-canvas text-text-primary",
        motionReady && "motion-ready",
      )}
    >
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>
      <Atmosphere />
      <ScrollDepth target="#top" />
      <CinematicField scene=".forecast-landing" ambient="#top" />
      <ParallaxField selector="[data-drift]" />
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
  as: Tag = "div",
  children,
  light = false,
  rule = true,
}: {
  as?: ElementType;
  children: ReactNode;
  light?: boolean;
  rule?: boolean;
}) {
  return (
    <Tag
      className={cn(
        "inline-flex items-center gap-3 font-mono text-site-caption font-normal uppercase tracking-[0.22em]",
        light ? "text-land-invert-muted" : "text-land-dim",
      )}
    >
      {rule ? (
        <span
          aria-hidden
          className={cn(
            "eyebrow-rule h-px w-7 shrink-0",
            light ? "bg-land-invert-accent" : "bg-accent",
          )}
        />
      ) : null}
      {children}
    </Tag>
  );
}

function Hero() {
  return (
    <section
      id="top"
      className="relative isolate overflow-hidden pb-[var(--section-gap)] pt-[calc(var(--nav-total)+clamp(2.5rem,5vw,4.5rem))]"
    >
      <div className="hero-atmos" aria-hidden>
        <span className="hero-wash depth-layer depth-wash absolute inset-x-0 top-[var(--nav-total)] mx-auto h-[min(54rem,76vw)] max-h-[620px] min-h-[360px] max-w-[1200px]" />
        <span className="aurora aurora-a" />
        <span className="aurora aurora-b" />
        <span className="aurora aurora-c" />
        <span className="hero-turn" />
        <span className="hero-beam" />
        <span className="hero-spot" />
        <span className="hero-scrim" />
        <span className="hero-vignette" />
      </div>

      <div className="page-shell flex flex-col items-center text-center">
        <div className="depth-layer depth-title flex flex-col items-center">
          <Reveal
            variant="fade"
            duration={420}
            className="flex items-center justify-center gap-3"
          >
            <span className="status-dot size-2 bg-accent" aria-hidden />
            <Eyebrow rule={false}>
              Demand forecasting for planning teams
            </Eyebrow>
          </Reveal>

          <SplitWords
            as="h1"
            text="See your demand before it arrives."
            delay={70}
            stagger={78}
            motion="cinematic"
            className="mt-6 max-w-[17ch] text-balance font-display text-site-display font-normal sm:mt-7"
          />

          <Reveal
            as="p"
            delay={150}
            duration={620}
            className="mt-5 max-w-[58ch] text-site-lead text-text-secondary"
          >
            Connect your sales history and see how much you will sell, week by
            week, with an honest range around every number.
          </Reveal>
        </div>

        <Reveal
          delay={240}
          duration={620}
          className="mt-8 flex w-full flex-col items-stretch justify-center gap-3 min-[430px]:w-auto min-[430px]:flex-row min-[430px]:items-center"
        >
          <PrimaryCta href="/signin">Start forecasting</PrimaryCta>
          <SecondaryCta href="/dashboard" label="Open the dashboard">
            Explore the live workspace
          </SecondaryCta>
        </Reveal>
        <Reveal
          delay={300}
          duration={520}
          className="mt-4 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 font-mono text-site-caption text-land-dim"
        >
          <span className="inline-flex items-center gap-1.5">
            <CheckCircle2 className="size-3.5 text-accent" aria-hidden /> No
            setup project
          </span>
          <span className="inline-flex items-center gap-1.5">
            <ShieldCheck className="size-3.5 text-accent" aria-hidden /> Figures
            stay traceable
          </span>
          <Link
            href="#how-it-works"
            className="link-draw text-accent hover:text-accent-hover"
          >
            See how it works ↓
          </Link>
        </Reveal>
      </div>

      <Reveal
        delay={330}
        variant="scale"
        duration={760}
        className="depth-layer depth-stage page-shell mt-10 sm:mt-12"
      >
        <div className="hero-stage">
          <span aria-hidden className="stage-sweep" />
          <div className="mb-5 border-b border-land-rule-soft pb-4">
            <p className="font-mono text-site-caption uppercase tracking-[0.15em] text-land-dim">
              Interactive forecast preview
            </p>
          </div>
          <DemandScape />
        </div>
      </Reveal>

      <Proof />
    </section>
  );
}

function Proof() {
  return (
    <div className="page-shell mt-14 sm:mt-16">
      <dl className="proof-band border-t border-land-rule">
        {PROOF.map((stat, index) => (
          <Reveal
            key={stat.label}
            delay={index * 130}
            duration={720}
            variant="scale"
            className="proof-figure"
          >
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
    <section id="how-it-works" className="section-edge section-pad">
      <div className={SHELL}>
        <div data-drift style={{ "--drift": "-74px" } as CSSProperties}>
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
        </div>

        <ScrollStage className="mt-12 sm:mt-16" stage="build">
          <div className="pipeline-grid">
            <ol className="pipeline-steps">
              {STEPS.map((step, index) => (
                <li key={step.title} className="pipeline-step">
                  <span
                    aria-hidden
                    className="pipeline-ordinal font-mono text-site-caption text-land-dim"
                  >
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <h3 className="font-display text-site-h3-display font-normal text-text-primary">
                      {step.title}
                    </h3>
                    <div className="pipeline-detail">
                      <div>
                        <p className="mt-2 max-w-[42ch] text-site-lead text-text-secondary">
                          {step.body}
                        </p>
                        <p className="mt-3 font-mono text-site-caption uppercase tracking-[0.14em] text-land-dim">
                          {step.foot}
                        </p>
                      </div>
                    </div>
                  </div>
                </li>
              ))}
            </ol>

            <div className="build-frame">
              <BuildStage />
            </div>
          </div>
        </ScrollStage>
      </div>
    </section>
  );
}

function Features() {
  return (
    <section id="features" className="section-edge section-pad">
      <ScrollStage screens={2.6} stage="filmstrip">
        <div className={cn(SHELL, "filmstrip")}>
          <Reveal variant="from-left" duration={640} className="filmstrip-head">
            <Eyebrow as="h2">What you get</Eyebrow>
          </Reveal>
          <ol className="filmstrip-track">
            {FEATURES.map((feature, index) => (
              <li key={feature.lede} className="filmstrip-panel">
                <span aria-hidden className="filmstrip-index font-mono">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <h3 className="filmstrip-lede text-balance font-display font-normal">
                  {feature.lede}
                </h3>
                <p className="filmstrip-body max-w-[42ch] text-site-lead text-text-secondary">
                  {feature.body}
                </p>
                <span aria-hidden className="filmstrip-rule" />
              </li>
            ))}
          </ol>
        </div>
      </ScrollStage>
    </section>
  );
}

function InsightsPreview() {
  const brief = useRef<HTMLDivElement>(null);
  useTilt(brief, 3.2);

  return (
    <section
      id="insights"
      className="section-edge section-edge--band section-pad bg-land-band"
    >
      <div
        className={cn(
          SHELL,
          "grid items-start gap-10 lg:grid-cols-[minmax(0,0.72fr)_minmax(0,1fr)] lg:gap-16",
        )}
      >
        <div data-drift style={{ "--drift": "-88px" } as CSSProperties}>
          <Reveal variant="from-left" duration={680}>
            <Eyebrow>Decision brief</Eyebrow>
            <SplitWords
              text="Know what changed, why it matters, and what to do next."
              stagger={54}
              motion="cinematic"
              className="mt-4 max-w-[22ch] text-balance font-display text-site-h2 font-normal"
            />
            <p className="mt-5 max-w-[46ch] text-site-lead text-text-secondary">
              Every run comes back with the handful of things worth acting on.
            </p>
            <div className="mt-7 grid gap-3 text-site-body text-text-secondary sm:grid-cols-2 lg:grid-cols-1">
              <p className="flex gap-3">
                <Target
                  className="mt-1 size-4 shrink-0 text-accent"
                  aria-hidden
                />
                <span>
                  <strong className="text-text-primary">Prioritised.</strong>{" "}
                  Risks and opportunities appear in decision order.
                </span>
              </p>
              <p className="flex gap-3">
                <ShieldCheck
                  className="mt-1 size-4 shrink-0 text-accent"
                  aria-hidden
                />
                <span>
                  <strong className="text-text-primary">Grounded.</strong> AI
                  may refine the wording; it never invents the figures.
                </span>
              </p>
            </div>
          </Reveal>
        </div>

        <div data-drift style={{ "--drift": "62px" } as CSSProperties}>
          <Reveal
            delay={120}
            variant="from-right"
            duration={720}
            className="tilt-scene"
          >
            <div
              ref={brief}
              className="tilt-plate border border-land-brief-border bg-land-brief"
            >
              <div className="flex items-center justify-between gap-4 border-b border-land-brief-rule px-5 py-4 sm:px-6">
                <div>
                  <p className="font-mono text-[0.68rem] uppercase tracking-[0.16em] text-land-dim">
                    Decision brief · this run
                  </p>
                  <p className="signal-heading mt-1 text-site-h3 font-bold">
                    Three signals need attention
                  </p>
                </div>
                <Sparkles
                  className="size-5 text-accent"
                  strokeWidth={1.7}
                  aria-hidden
                />
              </div>

              <ol className="signal-list">
                {SIGNALS.map((signal, index) => (
                  <li
                    key={signal.label}
                    className={cn("signal-row", `signal-row--${signal.tone}`)}
                    style={{ "--signal-index": index } as CSSProperties}
                  >
                    <span
                      aria-hidden
                      className="signal-index font-mono text-[0.68rem] text-land-dim"
                    >
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <div className="signal-body">
                      <p className="signal-label font-mono text-[0.68rem] uppercase tracking-[0.14em]">
                        {signal.label}
                      </p>
                      <p className="signal-title mt-1.5 text-site-h3 font-bold">
                        {signal.title}
                      </p>
                      <p className="mt-1.5 text-site-body text-text-secondary">
                        {signal.body}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>

              <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-land-brief-rule px-5 py-3 font-mono text-[0.68rem] text-land-dim sm:px-6">
                <span>Computed from 5 backtest folds</span>
                <span className="inline-flex items-center gap-1.5 text-accent">
                  <span className="size-1.5 bg-accent" aria-hidden /> Figures
                  verified
                </span>
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

function Compare() {
  const panels = useRef<HTMLDivElement>(null);
  useTilt(panels, 2.6);

  return (
    <section id="compare" className="section-edge section-pad">
      <div
        className={cn(
          SHELL,
          "grid gap-10 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1fr)] lg:gap-16",
        )}
      >
        <div data-drift style={{ "--drift": "-88px" } as CSSProperties}>
          <Reveal variant="from-left" duration={680}>
            <Eyebrow>Built for a real decision</Eyebrow>
            <SplitWords
              text="A range tells you more than a perfect-looking line."
              stagger={58}
              motion="cinematic"
              className="mt-4 max-w-[24ch] text-balance font-display text-site-h2 font-normal"
            />
            <p className="mt-5 max-w-[46ch] text-site-lead text-text-secondary">
              What is most likely, how far it could move, and what changed since
              the last run.
            </p>
            <p className="mt-7 font-mono text-site-caption uppercase tracking-[0.14em] text-land-dim">
              One answer, with the uncertainty left in
            </p>
          </Reveal>
        </div>
        <div data-drift style={{ "--drift": "62px" } as CSSProperties}>
          <Reveal
            delay={120}
            variant="from-right"
            duration={720}
            className="tilt-scene"
          >
            <div ref={panels} className="tilt-plate">
              <RangeVsLine />
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

const ACCURACY_BEATS = [
  "Measured against your own history, never a benchmark: we hide part of your past and check whether the forecast would have got it right.",
  "And every run adds another real result to it — any product, any region, any week.",
];

const BEAT_RAMP = 11;

const BEAT_OVERLAP = 1 / (2 * BEAT_RAMP);

function beatWindow(index: number): CSSProperties {
  const count = ACCURACY_BEATS.length;
  return {
    "--in": index === 0 ? -1 : index / count - BEAT_OVERLAP,
    "--out": index === count - 1 ? 2 : (index + 1) / count + BEAT_OVERLAP,
  } as CSSProperties;
}

function Accuracy() {
  return (
    <section id="accuracy" className="accuracy-scene bg-land-invert text-land-invert-ink">
      <span aria-hidden className="accuracy-veil">
        <span className="accuracy-halo" />
      </span>
      <ScrollStage screens={2.6} stage="accuracy">
        <div className={cn(SHELL, "accuracy-hold")}>
          <Reveal variant="fade" duration={680}>
            <Eyebrow light>Accuracy</Eyebrow>
          </Reveal>

          <p className="accuracy-figure mt-7 font-display text-accuracy font-normal leading-[0.86] tracking-[-0.03em] text-land-invert-accent">
            <CountUp value={94} />%
          </p>

          <h2 className="mt-6 max-w-[20ch] text-balance font-display text-site-h2 font-normal">
            of the sales it had never seen.
          </h2>

          <div className="accuracy-beats mt-8">
            {ACCURACY_BEATS.map((text, index) => (
              <p
                key={text}
                className="accuracy-beat text-site-lead text-land-invert-secondary"
                style={beatWindow(index)}
              >
                {text}
              </p>
            ))}
          </div>

          <ol className="accuracy-ticks" aria-hidden>
            {ACCURACY_BEATS.map((text, index) => (
              <li key={text} className="accuracy-tick" style={beatWindow(index)} />
            ))}
          </ol>
        </div>
      </ScrollStage>
    </section>
  );
}

function Closing() {
  return (
    <section className="section-pad">
      <Reveal
        variant="scale"
        duration={700}
        className="closing-panel page-shell text-center"
      >
        <Eyebrow>Start with the data you have</Eyebrow>
        <SplitWords
          text="See what is coming next."
          stagger={80}
          motion="cinematic"
          className="mt-4 text-balance font-display text-site-h2 font-normal"
        />
        <p className="mx-auto mt-5 max-w-[42ch] text-site-lead text-text-secondary">
          Bring the sales history you already have. The first forecast takes
          about a minute.
        </p>

        <div className="mt-8 flex w-full flex-col items-stretch justify-center gap-3 min-[430px]:mx-auto min-[430px]:w-auto min-[430px]:flex-row min-[430px]:items-center">
          <PrimaryCta href="/signin">Start forecasting</PrimaryCta>
          <SecondaryCta href="/dashboard">
            Explore the live workspace
          </SecondaryCta>
        </div>

        <p className="mt-6 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 font-mono text-site-caption text-land-dim">
          <span className="inline-flex items-center gap-1.5">
            <CheckCircle2 className="size-3.5 text-accent" aria-hidden /> No
            setup project
          </span>
          <span className="inline-flex items-center gap-1.5">
            <ShieldCheck className="size-3.5 text-accent" aria-hidden /> Figures
            stay traceable
          </span>
        </p>
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
        className={cn(
          SHELL,
          "flex flex-col gap-6 py-8 sm:flex-row sm:items-center",
        )}
      >
        <div className="flex items-center gap-3">
          <Mark size={28} />
          <span className="text-site-h3 font-bold">Forecast Hub</span>
        </div>
        <p className="text-site-body text-land-dim sm:ml-auto">
          Demand forecasting for planning teams.
        </p>
        <div className="flex items-center gap-5">
          <Link
            href="/signin"
            className="link-draw font-mono text-site-caption uppercase tracking-[0.11em] text-accent hover:text-accent-hover"
          >
            Sign in
          </Link>
          <Link
            href="/dashboard"
            className="link-draw font-mono text-site-caption uppercase tracking-[0.11em] text-accent hover:text-accent-hover"
          >
            Live workspace →
          </Link>
        </div>
      </Reveal>
    </footer>
  );
}
