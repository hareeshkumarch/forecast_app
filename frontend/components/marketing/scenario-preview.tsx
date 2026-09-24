"use client";

import Link from "next/link";
import { useState } from "react";

import { Reveal } from "@/components/marketing/reveal";

const BASE = [82, 91, 87, 103, 108, 99, 117, 126];
const SCENARIOS = [
  { label: "Base plan", change: 0, detail: "A starting point for the next eight weeks." },
  { label: "Demand lift", change: 20, detail: "Explore what 20% more demand would mean for your plan." },
  { label: "Softer demand", change: -15, detail: "Stress-test your plan with 15% less demand." },
] as const;

export function ScenarioPreview() {
  const [selected, setSelected] = useState(0);
  const scenario = SCENARIOS[selected] ?? SCENARIOS[0];
  const values = BASE.map((value) => Math.round(value * (1 + scenario.change / 100)));
  const total = values.reduce((sum, value) => sum + value, 0);

  return (
    <section id="scenario-preview" className="section-edge section-pad">
      <div className="page-shell grid items-center gap-10 lg:grid-cols-2 lg:gap-16">
        <Reveal variant="from-left">
          <p className="font-mono text-site-caption uppercase tracking-[0.2em] text-land-dim">Explore the possibilities</p>
          <h2 className="mt-4 max-w-[20ch] text-balance font-display text-site-h2">One forecast. More ways to prepare.</h2>
          <p className="mt-5 max-w-[43ch] text-site-lead text-text-secondary">Try a change in demand and watch the plan respond. In your workspace, build scenarios from your own forecast.</p>
          <Link href="/scenarios" className="link-draw mt-6 inline-block text-accent">Explore scenarios →</Link>
        </Reveal>
        <Reveal variant="scale" className="scenario-preview border border-land-rule bg-land-brief p-5 sm:p-8">
          <div className="flex flex-wrap gap-2" role="group" aria-label="Demand scenario">
            {SCENARIOS.map((item, index) => (
              <button
                key={item.label}
                type="button"
                aria-pressed={selected === index}
                onClick={() => setSelected(index)}
                className="scenario-choice min-h-11 rounded-full border border-land-rule px-4 py-2 text-site-caption transition-colors hover:border-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
              >{item.label}</button>
            ))}
          </div>
          <div className="mt-7 flex items-baseline justify-between gap-4" aria-live="polite" aria-atomic="true">
            <p><strong className="font-display text-site-h2 font-normal tabular-nums">{total.toLocaleString("en-US")}</strong><span className="ml-2 text-site-caption text-land-dim">units</span></p>
            <span className="font-mono text-site-caption text-accent">{scenario.change > 0 ? "+" : ""}{scenario.change}% vs base</span>
          </div>
          <div className="scenario-bars mt-6" role="img" aria-label={`${scenario.label}: ${values.map((value, index) => `week ${index + 1}, ${value} units`).join("; ")}`}>
            {values.map((value, index) => (
              <div key={index} className="scenario-column" aria-hidden="true">
                <div className="scenario-bar-track">
                  <span className="scenario-base" style={{ height: `${(BASE[index] ?? 0) / 1.6}%` }} />
                  <span className="scenario-bar" style={{ height: `${value / 1.6}%`, transitionDelay: `${index * 25}ms` }} />
                </div>
                <span className="font-mono text-site-caption text-land-dim">W{index + 1}</span>
              </div>
            ))}
          </div>
          <p className="mt-5 min-h-12 text-site-body text-text-secondary">{scenario.detail}</p>
          <p className="mt-4 border-t border-land-rule pt-4 font-mono text-site-caption text-land-dim">Illustrative data · assumption-based scenario, not a prediction</p>
        </Reveal>
      </div>
    </section>
  );
}
