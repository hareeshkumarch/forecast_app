import { ArrowUpRight, ArrowDownRight, Minus, MoveHorizontal } from "lucide-react";
import Link from "next/link";

import { Reveal } from "@/components/marketing/reveal";

const REVIEWS = [
  {
    name: "Chilled goods",
    region: "West region",
    signal: "Demand is softening",
    action: "Compare planned receipts with the lower forecast range.",
    label: "Review receipts",
    icon: ArrowDownRight,
    tone: "review",
  },
  {
    name: "Ambient goods",
    region: "All regions",
    signal: "Close to the recent baseline",
    action: "Check the next forecast run for a change in direction.",
    label: "Monitor demand",
    icon: Minus,
    tone: "steady",
  },
  {
    name: "Seasonal goods",
    region: "Online channel",
    signal: "A wider range of outcomes",
    action: "Compare stronger and softer demand before committing stock.",
    label: "Explore a scenario",
    icon: MoveHorizontal,
    tone: "range",
  },
] as const;

export function ForecastReview() {
  return (
    <section id="scenario-preview" className="section-edge section-pad">
      <div className="page-shell grid items-center gap-10 lg:grid-cols-[0.85fr_1.15fr] lg:gap-16">
        <Reveal variant="from-left">
          <p className="font-mono text-site-caption uppercase tracking-[0.2em] text-land-dim">04 — Forecast review</p>
          <h2 className="mt-4 max-w-[20ch] text-balance font-display text-site-h2">Know where to look.<br /><em className="text-accent">And what to review.</em></h2>
          <p className="mt-5 max-w-[43ch] text-site-lead text-text-secondary">See which products need a closer look. Connect changes in demand to the inventory questions your team needs to answer.</p>
          <Link href="/series" className="link-draw mt-6 inline-flex items-center gap-2 text-accent">Explore your sales series <ArrowUpRight className="size-4" aria-hidden /></Link>
        </Reveal>
        <Reveal variant="scale" className="forecast-review border border-land-rule bg-land-brief">
          <div className="forecast-review-heading">
            <div>
              <p className="font-mono text-site-caption uppercase tracking-[0.16em] text-land-dim">From forecast to follow-up</p>
              <h3 className="mt-2 font-display text-site-h3-display">The next decisions.</h3>
            </div>
            <span className="forecast-review-count">03</span>
          </div>
          <ul className="forecast-review-list">
            {REVIEWS.map(({ name, region, signal, action, label, icon: Icon, tone }) => (
              <li key={name} className="forecast-review-item" data-tone={tone}>
                <span className="forecast-review-icon"><Icon className="size-5" strokeWidth={1.5} aria-hidden /></span>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                    <h4 className="text-site-body font-semibold">{name}</h4>
                    <span className="font-mono text-site-caption text-land-dim">{region}</span>
                  </div>
                  <p className="mt-1 text-site-body text-text-secondary">{signal}</p>
                  <p className="forecast-review-action">{label}</p>
                  <p className="mt-2 text-site-body text-text-secondary">{action}</p>
                </div>
              </li>
            ))}
          </ul>
          <div className="forecast-review-footer">
            <p className="font-mono text-site-caption text-land-dim">Illustrative review · your results depend on your data</p>
            <Link href="/dashboard" className="link-draw inline-flex shrink-0 items-center gap-2 text-site-body text-accent">Review forecasts <ArrowUpRight className="size-4" aria-hidden /></Link>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
