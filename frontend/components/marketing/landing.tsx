"use client";

import { BarChart3, CirclePlay, FileUp, Gauge, Layers3, Table2 } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { CheckDiagram } from "@/components/marketing/check-diagram";
import { DemandScape } from "@/components/marketing/demand-scape";
import { Arrow, FloatingNav } from "@/components/marketing/floating-nav";
import { Mark } from "@/components/marketing/mark";
import { Reveal, useMotionReady } from "@/components/marketing/reveal";
import { cn } from "@/lib/utils";

const SHELL = "mx-auto w-full max-w-[1816px] px-6 sm:px-10 lg:px-[4.55rem]";

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
    <section id="top" className="pb-24 pt-[var(--nav-total)] sm:pb-28">
      <div className="mx-auto flex min-h-[calc(100svh-var(--nav-total))] flex-col justify-center px-5 text-center sm:px-8">
        <Reveal className="flex items-center justify-center gap-3">
          <span className="size-2 bg-[#287b59]" aria-hidden />
          <Eyebrow>Demand forecasting for planning teams</Eyebrow>
        </Reveal>

        <Reveal
          as="h1"
          delay={70}
          className="mx-auto mt-9 max-w-[940px] text-balance text-site-display font-bold sm:mt-10"
        >
          See your demand before it arrives.
        </Reveal>

        <Reveal as="p" delay={140} className="mx-auto mt-9 max-w-[820px] text-site-lead text-[#3f463f]">
          Connect your sales history and see how much you will sell, week by week, with an honest
          range around every number.
        </Reveal>

        <Reveal delay={210} className="mt-9 sm:mt-10">
          <Link
            href="/dashboard"
            className="group inline-flex h-[80px] items-center gap-5 bg-[#111512] px-10 text-site-lead font-medium text-white transition-colors hover:bg-[#242a25] sm:h-[82px] sm:px-11"
          >
            Open the dashboard
            <Arrow />
          </Link>
        </Reveal>
      </div>

      <Reveal delay={280} className="mx-auto mt-12 w-[118%] -translate-x-[7.5%] px-1 sm:mt-14 sm:w-full sm:translate-x-0 sm:px-8 lg:px-20">
        <DemandScape />
      </Reveal>
    </section>
  );
}

function HowItWorks() {
  return (
    <section id="how-it-works" className="border-t border-[#d8ddd7] py-24 sm:py-32">
      <div className={cn(SHELL, "grid gap-14 lg:grid-cols-[minmax(360px,.75fr)_minmax(0,1.55fr)] lg:gap-20")}>
        <Reveal>
          <Eyebrow>01 — Getting started</Eyebrow>
          <h2 className="mt-7 max-w-[540px] text-balance text-site-h2 font-bold">
            From a spreadsheet to a plan in three steps.
          </h2>
          <p className="mt-8 text-site-lead text-[#4e554e]">Nothing to configure. Nothing to maintain.</p>
        </Reveal>

        <div className="grid gap-4 md:grid-cols-2">
          {STEPS.map((step, index) => (
            <Reveal
              key={step.title}
              delay={index * 90}
              className={cn(
                "flex min-h-[415px] flex-col border bg-[#fafbf9] p-8",
                step.active ? "border-[#111512] bg-[#e5e8e3]" : "border-[#cfd5cf]",
              )}
            >
              <div className="flex items-center justify-between">
                <span className={cn("flex size-12 items-center justify-center border text-[15px]", step.active ? "border-[#111512] bg-[#111512] text-white" : "border-[#bcc4bc] text-[#59605a]")}>
                  {index + 1}
                </span>
                <step.icon className="size-5 text-[#59605a]" strokeWidth={1.8} aria-hidden />
              </div>
              <h3 className="mt-7 text-site-h3 font-bold">{step.title}</h3>
              <p className="mt-3 max-w-[48ch] text-site-body text-[#495049]">{step.body}</p>
              <p className="mt-auto pt-8 font-mono text-site-caption text-[#626862]">{step.foot}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function Features() {
  return (
    <section id="features" className="border-t border-[#d8ddd7] py-24 sm:py-32">
      <div className={SHELL}>
        <Reveal>
          <Eyebrow>What you get</Eyebrow>
          <h2 className="mt-7 max-w-[850px] text-balance text-site-h2 font-bold">
            Everything a planner needs, and nothing they do not.
          </h2>
        </Reveal>

        <div className="mt-16 grid border-l border-t border-[#cfd5cf] md:grid-cols-2 2xl:grid-cols-3">
          {FEATURES.map((feature, index) => (
            <Reveal key={feature.title} delay={index * 80} className="min-h-[330px] border-b border-r border-[#cfd5cf] bg-[#fafbf9]/70 p-8 sm:p-10">
              <div className="flex items-center justify-between font-mono text-site-caption uppercase tracking-[0.16em] text-[#697069]">
                {feature.number}
                <feature.icon className="size-5" strokeWidth={1.6} aria-hidden />
              </div>
              <h3 className="mt-16 text-site-h3 font-bold">{feature.title}</h3>
              <p className="mt-4 max-w-[48ch] text-site-body text-[#4c534d]">{feature.body}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function Compare() {
  return (
    <section id="compare" className="border-t border-[#d8ddd7] py-24 sm:py-32">
      <div className={cn(SHELL, "grid items-end gap-14 lg:grid-cols-2 lg:gap-24")}>
        <Reveal>
          <Eyebrow>Built for a real decision</Eyebrow>
          <h2 className="mt-7 max-w-[720px] text-balance text-site-h2 font-bold">
            A range tells you more than a perfect-looking line.
          </h2>
        </Reveal>
        <Reveal delay={100} className="border-l-2 border-[#287b59] pl-8">
          <p className="max-w-[46ch] text-site-lead text-[#3f463f]">
            Forecast Hub shows what is most likely, how far it could move, and what changed since the last run.
          </p>
          <p className="mt-7 font-mono text-site-caption uppercase tracking-[0.14em] text-[#747b74]">One answer, with the uncertainty left in</p>
        </Reveal>
      </div>
    </section>
  );
}

function Accuracy() {
  return (
    <section id="accuracy" className="bg-[#111512] py-28 text-[#f2f3f1] sm:py-40">
      <div className={cn(SHELL, "grid gap-20 lg:grid-cols-[minmax(0,.9fr)_minmax(520px,1.12fr)] lg:gap-28")}>
        <Reveal>
          <Eyebrow light>Accuracy</Eyebrow>
          <h2 className="mt-7 max-w-[700px] text-balance text-site-h2 font-bold">
            Right about <span className="text-[#287b59]">94%</span> of the sales it had never seen.
          </h2>
          <p className="mt-9 max-w-[700px] text-site-lead text-[#b9bdb9]">
            That figure comes from your own history, not a benchmark. You can see it for any product,
            any region, any week — and watch it change as your sales change.
          </p>
        </Reveal>

        <Reveal delay={100}>
          <CheckDiagram />
          <div className="mt-14 border border-white/20">
            <div className="p-7 sm:p-8">
              <h3 className="text-site-h3 font-bold">It is measured, not claimed</h3>
              <p className="mt-3 max-w-[62ch] text-site-body text-[#afb4af]">
                Before you ever see a number, we hide part of your own sales history and check whether the forecast would have got it right.
              </p>
            </div>
            <div className="border-t border-white/15 p-7 sm:p-8">
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
    <section className="py-28 sm:py-36">
      <Reveal className="mx-auto max-w-[980px] px-6 text-center">
        <Eyebrow>Start with the data you have</Eyebrow>
        <h2 className="mt-7 text-balance text-site-h2 font-bold">See what is coming next.</h2>
        <Link href="/dashboard" className="group mt-10 inline-flex h-[76px] items-center gap-5 bg-[#111512] px-10 text-site-lead font-medium text-white hover:bg-[#242a25]">
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
      <div className={cn(SHELL, "flex flex-col gap-8 py-10 sm:flex-row sm:items-center")}>
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
