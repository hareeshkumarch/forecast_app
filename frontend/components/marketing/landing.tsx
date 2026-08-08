"use client";

import {
  ArrowRight,
  Check,
  CirclePlay,
  Database,
  FileSpreadsheet,
  Github,
  Server,
  TrendingUp,
  Upload,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";
import { useEffect, useState } from "react";

import { DashboardPreview } from "@/components/marketing/dashboard-preview";
import { Reveal, useMotionReady } from "@/components/marketing/reveal";
import { cn } from "@/lib/utils";

const REPO_URL = "https://github.com/hareeshkumarch/forecast_app";

const SHELL = "mx-auto w-full max-w-[1360px] px-4 sm:px-6 lg:px-8";

const NAV_LINKS = [
  { href: "#method", label: "How it works" },
  { href: "#data", label: "Your data" },
  { href: "#selfhost", label: "Self-host" },
];

const STEPS: { icon: LucideIcon; title: string; body: string }[] = [
  {
    icon: Upload,
    title: "Bring in some data",
    body: "Upload a spreadsheet, or pull a table straight from a source you have connected.",
  },
  {
    icon: Database,
    title: "Say what to forecast",
    body: "It suggests the date and value columns. Confirm the pair and how often you report.",
  },
  {
    icon: CirclePlay,
    title: "Run it",
    body: "Several approaches are tested against real history. The strongest result fills the dashboard.",
  },
];

const FOLDS = [64, 72, 80, 88, 96];

const DATA_PATHS: { icon: LucideIcon; title: string; body: string }[] = [
  {
    icon: FileSpreadsheet,
    title: "Files",
    body: "Start quickly with CSV, Excel, or a spreadsheet.",
  },
  {
    icon: Database,
    title: "Databases",
    body: "Connect the operational database you already use.",
  },
  {
    icon: Server,
    title: "Warehouses and APIs",
    body: "Pull a table from your warehouse or a REST endpoint.",
  },
];

const FOOTER_COLUMNS = [
  {
    title: "Product",
    links: [
      { href: "/dashboard", label: "Dashboard" },
      { href: "#method", label: "How it works" },
    ],
  },
  {
    title: "Docs",
    links: [
      { href: `${REPO_URL}#readme`, label: "README" },
    ],
  },
  {
    title: "Source",
    links: [
      { href: REPO_URL, label: "GitHub" },
      { href: `${REPO_URL}#licence`, label: "Licence" },
    ],
  },
];

/* -------------------------------------------------------------- fragments */

function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <div className="font-mono text-caption uppercase tracking-[0.08em] text-text-muted">
      {children}
    </div>
  );
}

function SectionTitle({
  children,
  size = "md",
  className,
}: {
  children: ReactNode;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  return (
    <h2
      className={cn(
        "mt-3.5 font-display font-normal text-text-primary",
        size === "sm" && "text-display-xs sm:text-display-sm",
        size === "md" && "text-display-sm sm:text-display-md",
        size === "lg" && "text-display-md sm:text-display-lg",
        className,
      )}
    >
      {children}
    </h2>
  );
}

const PRIMARY_CTA = cn(
  "inline-flex items-center justify-center gap-2 rounded-[10px] border border-accent bg-accent",
  "font-medium text-on-accent transition-[background-color,box-shadow] duration-200",
  "hover:bg-accent-hover hover:shadow-[0_8px_20px_-14px_var(--accent)]",
);

const SECONDARY_CTA = cn(
  "inline-flex items-center justify-center gap-2 rounded-[10px] border border-border-strong bg-surface",
  "font-medium text-text-primary transition-colors duration-200 hover:bg-surface-muted",
);

const CARD = cn(
  "rounded-[14px] border border-border bg-surface transition-[box-shadow,border-color] duration-200",
  "hover:border-border-strong hover:shadow-[0_10px_24px_-20px_var(--overlay)]",
);

function delayVar(ms: number, key: string): CSSProperties {
  return { [key]: `${ms}ms` } as CSSProperties;
}

/* ------------------------------------------------------------------ page */

export function Landing() {
  const motionReady = useMotionReady();

  return (
    <div
      className={cn(
        "min-h-screen bg-canvas font-plex text-body text-text-primary antialiased",
        motionReady && "motion-ready",
      )}
    >
      <SiteNav />

      <main id="main-content">
        <Hero />
        <Preview />
        <Steps />
        <Method />
        <Connectors />
        <SelfHost />
        <ClosingCta />
      </main>

      <SiteFooter />
    </div>
  );
}

/* ------------------------------------------------------------------- nav */

function SiteNav() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={cn(
        "sticky top-0 z-20 border-b bg-canvas/[0.86] backdrop-blur-[12px]",
        "transition-[border-color,box-shadow] duration-300",
        scrolled ? "border-border shadow-[0_1px_12px_-6px_var(--overlay)]" : "border-transparent",
      )}
    >
      <div className={cn(SHELL, "flex h-16 items-center gap-7")}>
        <a href="#top" className="flex shrink-0 items-center gap-2.5 text-text-primary">
          <span
            className="flex h-[30px] w-[30px] items-center justify-center rounded-[9px] bg-accent"
            aria-hidden
          >
            <TrendingUp className="h-[15px] w-[15px] text-on-accent" />
          </span>
          <span className="text-title font-semibold tracking-[-0.01em]">Forecast Hub</span>
        </a>

        {/* From lg, not md: at 768 the four labels and the CTA together leave the
            links no room and each one wraps onto two lines. */}
        <nav aria-label="Sections" className="ml-1 hidden gap-6 lg:flex">
          {NAV_LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="inline-flex min-h-11 items-center whitespace-nowrap text-subhead text-text-secondary transition-colors duration-fast hover:text-text-primary"
            >
              {link.label}
            </a>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-3.5">
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            className="hidden min-h-11 items-center text-subhead text-text-secondary transition-colors duration-fast hover:text-text-primary sm:inline-flex"
          >
            Docs
          </a>
          {/* The full label wraps to two lines below ~360px and spills out of a
              fixed-height pill, so the narrowest phones get the short form. The
              accessible name stays the same at every width. */}
          <Link
            href="/dashboard"
            aria-label="Open the dashboard"
            className={cn(PRIMARY_CTA, "h-11 shrink-0 whitespace-nowrap px-4 text-subhead")}
          >
            <span className="sm:hidden">Dashboard</span>
            <span className="hidden sm:inline">Open the dashboard</span>
          </Link>
        </div>
      </div>
    </header>
  );
}

/* ------------------------------------------------------------------ hero */

function Hero() {
  return (
    <section id="top" className="relative overflow-hidden">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[620px]" aria-hidden>
        <div className="hero-wash h-full w-full" />
      </div>

      <div className={cn(SHELL, "relative pt-20 sm:pt-24")}>
        <div className="max-w-[760px]">
          <Reveal className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-gold" aria-hidden />
            <Eyebrow>Demand forecasting, without the guesswork</Eyebrow>
          </Reveal>

          <Reveal
            as="h1"
            delay={90}
            className="mt-6 font-display text-[44px] font-normal leading-[1.04] tracking-[-0.02em] text-text-primary sm:text-display-lg lg:text-display-xl"
          >
            Turn sales history into
            <br />
            a forecast you can trust.
          </Reveal>

          <Reveal as="p" delay={180} className="mt-7 max-w-[600px] text-lead text-text-secondary">
            Connect your sales history and get a forecast that has already been checked against
            what actually happened. You see the outlook, uncertainty, and business drivers in one
            decision-ready workspace.
          </Reveal>

          <Reveal delay={270} className="mt-9 flex flex-wrap gap-3">
            <Link href="/dashboard" className={cn(PRIMARY_CTA, "h-11 px-6 text-[15px]")}>
              Open the dashboard
              <ArrowRight className="h-[15px] w-[15px]" aria-hidden />
            </Link>
            <a href="#selfhost" className={cn(SECONDARY_CTA, "h-11 px-6 text-[15px]")}>
              Self-host it
            </a>
          </Reveal>

          <Reveal as="p" delay={340} className="mt-6 font-mono text-meta text-text-muted">
            MIT licensed · runs on your own machine · no account needed
          </Reveal>
        </div>
      </div>
    </section>
  );
}

/* --------------------------------------------------------------- preview */

function Preview() {
  return (
    <section id="demo" className={cn(SHELL, "pt-16 sm:pt-20")}>
      <Reveal className="mb-7 flex flex-wrap items-end justify-between gap-5 sm:mb-9">
        <div className="max-w-[620px]">
          <Eyebrow>A planning workspace, not a black box</Eyebrow>
          <SectionTitle size="sm">See the forecast, the range, and what moved it.</SectionTitle>
        </div>
        <p className="max-w-[440px] text-subhead leading-[1.65] text-text-secondary">
          A decision-ready view of the next twelve months, with the drivers and risks kept close to
          the numbers they explain.
        </p>
      </Reveal>
      <DashboardPreview />
    </section>
  );
}

/* ----------------------------------------------------------------- steps */

function Steps() {
  return (
    <section className={cn(SHELL, "pt-24 sm:pt-28")}>
      <div className="grid gap-10 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)] lg:gap-16">
        <Reveal>
          <Eyebrow>01 — Getting started</Eyebrow>
          <SectionTitle>Three steps from raw history to a useful forecast.</SectionTitle>
          <p className="mt-4 text-[15px] leading-[1.65] text-text-secondary">
            No technical setup up front. It proposes, you confirm.
          </p>
        </Reveal>

        <div className="grid gap-4 sm:grid-cols-3">
          {STEPS.map((step, index) => {
            const last = index === STEPS.length - 1;
            return (
              <Reveal
                key={step.title}
                delay={index * 110}
                className={cn(
                  CARD,
                  "p-5",
                  last && "border-accent-border bg-accent-soft hover:border-accent-border",
                )}
              >
                <div className="flex items-center gap-2.5">
                  <span
                    className={cn(
                      "flex h-[26px] w-[26px] items-center justify-center rounded-full border text-meta font-semibold",
                      last
                        ? "border-accent-border bg-surface text-accent"
                        : "border-border-strong bg-surface-muted text-text-secondary",
                    )}
                    aria-hidden
                  >
                    {index + 1}
                  </span>
                  <step.icon
                    className={cn("h-[15px] w-[15px]", last ? "text-accent" : "text-text-muted")}
                    aria-hidden
                  />
                </div>
                <div className="mt-4 text-[15px] font-semibold text-text-primary">{step.title}</div>
                <p className="mt-2 text-subhead leading-[1.6] text-text-secondary">{step.body}</p>
              </Reveal>
            );
          })}
        </div>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- method */

function Method() {
  return (
    <section
      id="method"
      className="mt-24 border-y border-border bg-surface sm:mt-28"
    >
      <div className={cn(SHELL, "py-20")}>
        <div className="grid gap-12 lg:grid-cols-2 lg:gap-20">
          <Reveal>
            <Eyebrow>02 — How the winner is chosen</Eyebrow>
            <SectionTitle>Backtested first, trusted second.</SectionTitle>
            <p className="mt-5 text-[15px] leading-[1.7] text-text-secondary">
              Every candidate is judged the honest way. Train it on what was known at the time, ask
              it to predict the stretch that came next, then compare against what actually happened
              — over and over, further along the history each time.
            </p>
            <p className="mt-4 text-[15px] leading-[1.7] text-text-secondary">
              A forecast only wins here by being right about data it had never seen. Slow,
              stop-start demand is scored differently, because the usual measures quietly reward
              predicting nothing at all.
            </p>

            <div className="mt-7 flex flex-wrap gap-2.5">
              {["Trained on the past", "Scored on the unseen", "Winner refits on everything"].map(
                (chip) => (
                  <span
                    key={chip}
                    className="inline-flex items-center rounded-[9px] border border-border bg-canvas px-3 py-2 font-mono text-meta text-text-secondary"
                  >
                    {chip}
                  </span>
                ),
              )}
            </div>
          </Reveal>

          <Reveal delay={120} className="overflow-hidden rounded-[14px] border border-border bg-canvas">
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <span className="text-subhead font-semibold text-text-primary">Rolling test</span>
              <span className="font-mono text-micro text-text-muted">5 rounds</span>
            </div>

            <div className="flex flex-col gap-3 p-5">
              {FOLDS.map((train, index) => (
                <div key={train} className="flex items-center gap-3">
                  <span className="w-14 shrink-0 font-mono text-micro text-text-muted">
                    round {index + 1}
                  </span>
                  <span
                    className="grow-x flex h-3 flex-1 overflow-hidden rounded-[4px]"
                    style={delayVar(index * 130, "--grow-delay")}
                  >
                    <span style={{ width: `${train - 28}%` }} className="bg-accent-border" />
                    <span style={{ width: "12%" }} className="bg-gold" />
                    <span className="flex-1 bg-surface-muted" />
                  </span>
                </div>
              ))}

              <div className="mt-1.5 flex flex-wrap gap-4">
                {[
                  { label: "trained on", className: "bg-accent-border" },
                  { label: "checked against", className: "bg-gold" },
                  { label: "still unseen", className: "bg-surface-muted" },
                ].map((key) => (
                  <span
                    key={key.label}
                    className="inline-flex items-center gap-2 text-meta text-text-secondary"
                  >
                    <span className={cn("h-2 w-3 rounded-[2px]", key.className)} aria-hidden />
                    {key.label}
                  </span>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-2.5 border-t border-border bg-surface px-5 py-4">
              <span
                className="flex h-5 w-5 items-center justify-center rounded-[6px] bg-positive-soft"
                aria-hidden
              >
                <Check className="h-3 w-3 text-positive" strokeWidth={2.6} />
              </span>
              <span className="text-body text-text-secondary">
                Best-performing forecast selected from results on unseen history.
              </span>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------ connectors */

function Connectors() {
  return (
    <section id="data" className={cn(SHELL, "pt-24 sm:pt-28")}>
      <div className="grid gap-10 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)] lg:gap-16">
        <Reveal>
          <Eyebrow>03 — Data in</Eyebrow>
          <SectionTitle>Use the data you already have.</SectionTitle>
          <p className="mt-4 text-[15px] leading-[1.65] text-text-secondary">
            Upload a file or connect a live source. Credentials stay inside your own deployment.
          </p>
        </Reveal>

        <div className="grid gap-3 sm:grid-cols-3">
          {DATA_PATHS.map((path, index) => (
            <Reveal key={path.title} delay={index * 60} className={cn(CARD, "p-5")}>
              <span className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-accent-soft text-accent">
                <path.icon className="h-4 w-4" aria-hidden />
              </span>
              <div className="mt-4 text-subhead font-semibold text-text-primary">{path.title}</div>
              <p className="mt-2 text-body leading-[1.6] text-text-secondary">{path.body}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------- self-host */

function SelfHost() {
  return (
    <section id="selfhost" className="mt-24 border-t border-border bg-surface sm:mt-28">
      <div className={cn(SHELL, "py-20")}>
        <div className="grid items-start gap-10 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,.95fr)] lg:gap-20">
          <Reveal className="max-w-[620px]">
            <Eyebrow>04 — Self-host</Eyebrow>
            <SectionTitle>Your forecast stack, on your infrastructure.</SectionTitle>
            <p className="mt-[18px] text-[15px] leading-[1.7] text-text-secondary">
              Run the database, API and app together, with no hosted account in the middle. You keep
              the data, the deployment and every forecast result under your control.
            </p>

            <div className="mt-6 flex flex-wrap gap-2.5">
              <a
                href={`${REPO_URL}#readme`}
                target="_blank"
                rel="noreferrer"
                className={cn(PRIMARY_CTA, "h-[42px] px-5 text-subhead")}
              >
                Read the docs
              </a>
              <a
                href={REPO_URL}
                target="_blank"
                rel="noreferrer"
                className={cn(SECONDARY_CTA, "h-[42px] px-5 text-subhead")}
              >
                <Github className="h-4 w-4" aria-hidden />
                View the repo
              </a>
            </div>
          </Reveal>

          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
            {[
              {
                icon: CirclePlay,
                title: "One coordinated stack",
                body: "The app, API and database ship together and stay versioned together.",
              },
              {
                icon: Database,
                title: "Private by default",
                body: "Source data and generated forecasts stay inside the environment you choose.",
              },
              {
                icon: Github,
                title: "Open and adaptable",
                body: "MIT licensed, inspectable, and ready to fit into the tools you already run.",
              },
            ].map((item, index) => (
              <Reveal
                key={item.title}
                delay={100 + index * 90}
                className="flex gap-4 rounded-[14px] border border-border bg-canvas p-4 sm:flex-col lg:flex-row"
              >
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] border border-accent-border bg-accent-soft text-accent">
                  <item.icon className="h-[18px] w-[18px]" aria-hidden />
                </span>
                <div>
                  <div className="text-subhead font-semibold text-text-primary">{item.title}</div>
                  <p className="mt-1.5 text-body leading-[1.6] text-text-secondary">{item.body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------ closing cta */

function ClosingCta() {
  return (
    <section className={cn(SHELL, "py-24 sm:py-28")}>
      <Reveal className="mx-auto max-w-[640px] text-center">
        <h2 className="font-display text-display-md font-normal text-text-primary sm:text-display-lg">
          See what your next twelve months could look like.
        </h2>
        <p className="mt-5 text-title leading-[1.65] text-text-secondary">
          The dashboard opens with sample retail history. Bring your own file and refresh the
          forecast in under a minute.
        </p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <Link href="/dashboard" className={cn(PRIMARY_CTA, "h-[46px] px-7 text-[15px]")}>
            Open the dashboard
            <ArrowRight className="h-[15px] w-[15px]" aria-hidden />
          </Link>
          <a href="#selfhost" className={cn(SECONDARY_CTA, "h-[46px] bg-transparent px-7 text-[15px]")}>
            Self-host it
          </a>
        </div>
      </Reveal>
    </section>
  );
}

/* ---------------------------------------------------------------- footer */

function SiteFooter() {
  return (
    <footer className="border-t border-border bg-surface">
      <div className={cn(SHELL, "py-12")}>
        <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr_1fr]">
          <div>
            <div className="flex items-center gap-2.5">
              <span
                className="flex h-[26px] w-[26px] items-center justify-center rounded-lg bg-accent"
                aria-hidden
              >
                <TrendingUp className="h-3.5 w-3.5 text-on-accent" />
              </span>
              <span className="text-subhead font-semibold text-text-primary">Forecast Hub</span>
            </div>
            <p className="mt-3.5 max-w-[280px] text-body leading-[1.6] text-text-muted">
              Clear forecasts, useful drivers, and practical planning in one workspace.
            </p>
          </div>

          {FOOTER_COLUMNS.map((column) => (
            <div key={column.title} className="flex flex-col gap-2.5">
              <div className="text-meta font-semibold uppercase tracking-[0.05em] text-text-muted">
                {column.title}
              </div>
              {column.links.map((link) =>
                link.href.startsWith("http") ? (
                  <a
                    key={link.label}
                    href={link.href}
                    target="_blank"
                    rel="noreferrer"
                    className="text-subhead text-text-secondary transition-colors duration-fast hover:text-accent"
                  >
                    {link.label}
                  </a>
                ) : link.href.startsWith("#") ? (
                  <a
                    key={link.label}
                    href={link.href}
                    className="text-subhead text-text-secondary transition-colors duration-fast hover:text-accent"
                  >
                    {link.label}
                  </a>
                ) : (
                  <Link
                    key={link.label}
                    href={link.href}
                    className="text-subhead text-text-secondary transition-colors duration-fast hover:text-accent"
                  >
                    {link.label}
                  </Link>
                ),
              )}
            </div>
          ))}
        </div>

        <div className="mt-11 border-t border-border pt-5">
          <span className="font-mono text-meta text-text-muted">
            MIT licensed · self-hosted · your data stays yours
          </span>
        </div>
      </div>
    </footer>
  );
}
