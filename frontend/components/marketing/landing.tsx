"use client";

import { BarChart3, CirclePlay, FileUp, Gauge, Layers3, Table2 } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { CheckDiagram } from "@/components/marketing/check-diagram";
import { CountUp } from "@/components/marketing/count-up";
import { DemandScape } from "@/components/marketing/demand-scape";
import { Arrow, FloatingNav } from "@/components/marketing/floating-nav";
import { Mark } from "@/components/marketing/mark";
import { RangeVsLine } from "@/components/marketing/range-vs-line";
import { Reveal, useMotionReady } from "@/components/marketing/reveal";
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
    <div className={cn("forecast-landing min-h-screen overflow-hidden bg-[#f1f3ef] text-[#111512]", motionReady && "motion-ready")}>
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

function Eyebrow({ children, light = false }: { children: ReactNode; light?: boolean }) {
  return (
    <div className={cn("font-mono text-site-caption uppercase tracking-[0.22em]", light ? "text-[#858b86]" : "text-[#626862]")}>
      {children}
    </div>
  );
}

function Hero() {
  return (
    <section id="top" className="pb-[var(--section-gap)] pt-[calc(var(--nav-total)+clamp(2.5rem,5vw,4.5rem))]">
      <div className="page-shell flex flex-col items-center text-center">
        <Reveal className="flex items-center justify-center gap-3">
          <span className="size-2 bg-[#287b59]" aria-hidden />
          <Eyebrow>Demand forecasting for planning teams</Eyebrow>
        </Reveal>

        <Reveal
          as="h1"
          delay={70}
          className="mt-6 max-w-[17ch] text-balance text-site-display font-bold sm:mt-7"
        >
          See your demand before it arrives.
        </Reveal>

        <Reveal as="p" delay={140} className="mt-5 max-w-[58ch] text-site-lead text-[#3f463f]">
          Connect your sales history and see how much you will sell, week by week, with an honest
          range around every number.
        </Reveal>

        <Reveal delay={210} className="mt-8">
          <Link
            href="/dashboard"
            className="cta-nudge group inline-flex h-[52px] items-center gap-3 border-2 border-[#111512] bg-[#111512] px-7 text-site-body font-medium text-white hover:border-[#287b59] hover:bg-[#242a25] sm:h-[56px] sm:px-8"
          >
            Open the dashboard
            <Arrow />
          </Link>
        </Reveal>
      </div>

      <Reveal delay={280} className="page-shell mt-10 sm:mt-12">
        <DemandScape />
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
      <dl className="grid border-l border-t border-[#cfd5cf] sm:grid-cols-2 xl:grid-cols-4">
        {PROOF.map((stat, index) => (
          <Reveal
            key={stat.label}
            delay={index * 70}
            className="border-b border-r border-[#cfd5cf] bg-[#fafbf9]/70 p-6 sm:p-7"
          >
            <dt className="text-stat font-bold text-[#111512]">
              {stat.count ? <CountUp value={stat.value} /> : stat.value}
              <span className="text-[#287b59]">{stat.unit}</span>
            </dt>
            <dd className="mt-2 max-w-[26ch] font-mono text-site-caption text-[#5d645e]">
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
    <section id="how-it-works" className="section-pad border-t border-[#d8ddd7]">
      <div className={cn(SHELL, "grid gap-10 xl:grid-cols-[minmax(0,0.5fr)_minmax(0,1fr)] xl:gap-12")}>
        <Reveal>
          <Eyebrow>01 — Getting started</Eyebrow>
          <h2 className="mt-4 max-w-[22ch] text-balance text-site-h2 font-bold">
            From a spreadsheet to a plan in three steps.
          </h2>
          <p className="mt-5 max-w-[36ch] text-site-lead text-[#4e554e]">Nothing to configure. Nothing to maintain.</p>
        </Reveal>

        <div className="grid gap-4 sm:grid-cols-2">
          {STEPS.map((step, index) => (
            <Reveal
              key={step.title}
              delay={index * 90}
              className={cn(
                "card-hover flex flex-col border bg-[#fafbf9] p-6 sm:p-7",
                step.active
                  ? "border-[#111512] bg-[#e5e8e3] sm:col-span-2"
                  : "border-[#cfd5cf] hover:border-[#8f9a90]",
              )}
            >
              <div className="flex items-center justify-between">
                <span className={cn("flex size-10 items-center justify-center border text-site-body", step.active ? "border-[#111512] bg-[#111512] text-white" : "border-[#bcc4bc] text-[#59605a]")}>
                  {index + 1}
                </span>
                <step.icon className="size-5 text-[#59605a]" strokeWidth={1.8} aria-hidden />
              </div>
              <h3 className="mt-5 text-site-h3 font-bold">{step.title}</h3>
              <p className="mt-2 max-w-[42ch] text-site-body text-[#495049]">{step.body}</p>
              <p className="mt-auto pt-6 font-mono text-site-caption text-[#626862]">{step.foot}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function Features() {
  return (
    <section id="features" className="section-pad border-t border-[#d8ddd7]">
      <div className={SHELL}>
        <Reveal>
          <Eyebrow>What you get</Eyebrow>
          <h2 className="mt-4 max-w-[26ch] text-balance text-site-h2 font-bold">
            Everything a planner needs, and nothing they do not.
          </h2>
        </Reveal>

        <div className="mt-10 grid border-l border-t border-[#cfd5cf] sm:grid-cols-2 xl:grid-cols-3">
          {FEATURES.map((feature, index) => (
            <Reveal key={feature.title} delay={index * 80} className="card-hover flex flex-col border-b border-r border-[#cfd5cf] bg-[#fafbf9]/70 p-6 hover:border-[#8f9a90] sm:p-8">
              <div className="flex items-center justify-between font-mono text-site-caption uppercase tracking-[0.16em] text-[#697069]">
                {feature.number}
                <feature.icon className="size-5" strokeWidth={1.6} aria-hidden />
              </div>
              <h3 className="mt-10 text-site-h3 font-bold">{feature.title}</h3>
              <p className="mt-2 max-w-[42ch] text-site-body text-[#4c534d]">{feature.body}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function Compare() {
  return (
    <section id="compare" className="section-pad border-t border-[#d8ddd7]">
      <div className={cn(SHELL, "grid gap-10 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1fr)] lg:gap-16")}>
        <Reveal>
          <Eyebrow>Built for a real decision</Eyebrow>
          <h2 className="mt-4 max-w-[24ch] text-balance text-site-h2 font-bold">
            A range tells you more than a perfect-looking line.
          </h2>
          <p className="mt-5 max-w-[46ch] text-site-lead text-[#3f463f]">
            Forecast Hub shows what is most likely, how far it could move, and what changed since the last run.
          </p>
          <p className="mt-7 font-mono text-site-caption uppercase tracking-[0.14em] text-[#747b74]">
            One answer, with the uncertainty left in
          </p>
        </Reveal>
        <Reveal delay={100}>
          <RangeVsLine />
        </Reveal>
      </div>
    </section>
  );
}

function Accuracy() {
  return (
    <section id="accuracy" className="section-pad bg-[#111512] text-[#f2f3f1]">
      <div className={cn(SHELL, "grid gap-12 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1fr)] lg:gap-16")}>
        <Reveal>
          <Eyebrow light>Accuracy</Eyebrow>
          <h2 className="mt-4 max-w-[24ch] text-balance text-site-h2 font-bold">
            Right about{" "}
            <span className="whitespace-nowrap text-[#287b59]">
              <CountUp value={94} />%
            </span>{" "}
            of the sales it had never seen.
          </h2>
          <p className="mt-5 max-w-[52ch] text-site-lead text-[#b9bdb9]">
            That figure comes from your own history, not a benchmark. You can see it for any product,
            any region, any week — and watch it change as your sales change.
          </p>
        </Reveal>

        <Reveal delay={100}>
          <CheckDiagram />
          <div className="mt-10 border border-white/20">
            <div className="p-6 sm:p-7">
              <h3 className="text-site-h3 font-bold">It is measured, not claimed</h3>
              <p className="mt-3 max-w-[62ch] text-site-body text-[#afb4af]">
                Before you ever see a number, we hide part of your own sales history and check whether the forecast would have got it right.
              </p>
            </div>
            <div className="border-t border-white/15 p-6 sm:p-7">
              <h3 className="text-site-h3 font-bold">It keeps being checked</h3>
              <p className="mt-3 max-w-[62ch] text-site-body text-[#afb4af]">Every new run adds another real result to the score.</p>
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
      <Reveal className="page-shell max-w-[46ch] text-center">
        <Eyebrow>Start with the data you have</Eyebrow>
        <h2 className="mt-4 text-balance text-site-h2 font-bold">See what is coming next.</h2>
        <Link href="/dashboard" className="cta-nudge group mt-8 inline-flex h-[52px] items-center gap-3 border-2 border-[#111512] bg-[#111512] px-7 text-site-body font-medium text-white hover:border-[#287b59] hover:bg-[#242a25] sm:h-[56px] sm:px-8">
          Open the dashboard
          <Arrow />
        </Link>
      </Reveal>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-[#cfd5cf] bg-[#fafbf9]/75">
      <div className={cn(SHELL, "flex flex-col gap-6 py-8 sm:flex-row sm:items-center")}>
        <div className="flex items-center gap-3">
          <Mark size={28} />
          <span className="text-site-h3 font-bold">Forecast Hub</span>
        </div>
        <p className="text-site-body text-[#737a73] sm:ml-auto">Demand forecasting for planning teams.</p>
        <Link href="/dashboard" className="font-mono text-site-caption uppercase tracking-[0.11em] text-[#287b59] hover:text-[#175a3e]">Open dashboard →</Link>
      </div>
    </footer>
  );
}
