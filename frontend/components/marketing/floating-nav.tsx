"use client";

import { Menu, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Mark } from "@/components/marketing/mark";
import { ThemeToggle } from "@/components/marketing/theme-toggle";
import { cn } from "@/lib/utils";

const SECTIONS = [
  { id: "how-it-works", label: "How it works" },
  { id: "features", label: "Features" },
  { id: "insights", label: "Insights" },
  { id: "compare", label: "Compare" },
  { id: "accuracy", label: "Accuracy" },
];

export function FloatingNav() {
  const [lifted, setLifted] = useState(false);
  const [pastHero, setPastHero] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [indicator, setIndicator] = useState<{ left: number; width: number } | null>(null);
  const placed = useRef(false);
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;

    const place = () => {
      const current = active
        ? list.querySelector<HTMLElement>(`[data-section="${active}"]`)
        : null;
      if (!current) {
        placed.current = false;
        setIndicator(null);
        return;
      }
      setIndicator({ left: current.offsetLeft, width: current.offsetWidth });
    };

    place();
    // The list's own width is content-driven and constant, so watching it
    // alone never fires. The nav around it is what changes with the viewport.
    const observer = new ResizeObserver(place);
    observer.observe(list);
    if (list.parentElement) observer.observe(list.parentElement);
    document.fonts?.ready.then(place).catch(() => undefined);
    return () => observer.disconnect();
  }, [active]);

  useEffect(() => {
    if (indicator) {
      const frame = requestAnimationFrame(() => {
        placed.current = true;
      });
      return () => cancelAnimationFrame(frame);
    }
    placed.current = false;
    return undefined;
  }, [indicator]);

  useEffect(() => {
    let frame = 0;
    const update = () => {
      setLifted(window.scrollY > 40);
      setPastHero(window.scrollY > 520);
    };
    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        update();
      });
    };

    update();
    window.addEventListener("scroll", onScroll, { passive: true });

    const targets = SECTIONS.map((section) => document.getElementById(section.id)).filter(
      (target): target is HTMLElement => target !== null,
    );
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: "-43% 0px -43% 0px", threshold: 0 },
    );

    targets.forEach((target) => observer.observe(target));
    return () => {
      window.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    if (!mobileOpen) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileOpen(false);
    };
    const desktop = window.matchMedia("(min-width: 1024px)");
    const onDesktop = () => {
      if (desktop.matches) setMobileOpen(false);
    };

    document.addEventListener("keydown", onKeyDown);
    desktop.addEventListener("change", onDesktop);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      desktop.removeEventListener("change", onDesktop);
    };
  }, [mobileOpen]);

  return (
    <div className="fixed inset-x-0 top-[var(--nav-inset)] z-50">
      <nav
        aria-label="Sections"
        className={cn(
          "page-shell relative flex h-[var(--nav-height)] items-center overflow-hidden border border-border bg-surface/95 px-3 backdrop-blur-xl transition-shadow duration-300 sm:px-5",
          lifted
            ? "shadow-[0_18px_38px_-22px_var(--land-nav-shadow)]"
            : "shadow-[0_4px_14px_-10px_var(--land-nav-shadow)]",
        )}
      >
        <Link href="#top" aria-label="Forecast Hub, back to top" className="flex shrink-0 items-center gap-2.5">
          <Mark size={24} />
          <span className="hidden text-site-h3 font-bold text-text-primary min-[360px]:inline">Forecast Hub</span>
        </Link>

        <ul ref={listRef} className="relative mx-auto hidden items-center gap-0.5 lg:flex">
          {/* The indicator slides between items rather than cutting. It marks
              a position, not a quantity, so it is allowed to overshoot. */}
          <span
            aria-hidden
            data-placing={placed.current ? undefined : "true"}
            className="nav-indicator pointer-events-none absolute inset-y-1 left-0 bg-surface-muted"
            style={{
              width: indicator?.width ?? 0,
              transform: `translate3d(${indicator?.left ?? 0}px, 0, 0)`,
              opacity: indicator ? 1 : 0,
            }}
          />
          {SECTIONS.map((section) => (
            <li key={section.id}>
              <Link
                href={`#${section.id}`}
                data-section={section.id}
                aria-current={active === section.id ? "location" : undefined}
                className={cn(
                  "relative inline-flex px-3.5 py-2 text-site-body text-text-secondary transition-colors hover:text-text-primary",
                  active === section.id && "text-text-primary",
                )}
              >
                {section.label}
              </Link>
            </li>
          ))}
        </ul>

        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />

          <Link
            href="/signin"
            className="hidden h-[40px] items-center px-2 text-site-body font-medium text-text-secondary transition-colors hover:text-text-primary min-[430px]:inline-flex sm:h-[42px] sm:px-3"
          >
            Sign in
          </Link>
          <Link
            href="/dashboard"
            aria-label="Open the dashboard"
            aria-hidden={!pastHero}
            tabIndex={pastHero ? 0 : -1}
            /*
             * Hidden by `visibility`, not by collapsing to nothing.
             *
             * The pill used to animate from `w-0`, which grew the group it
             * sits in from 48px to 260px the moment the hero scrolled past
             * and shoved the section list sideways — a layout shift, small
             * but real, and the only one on the page. Reserving the width
             * costs an empty slot at the right of the nav that nobody can
             * see, and buys a nav that never moves.
             *
             * `visibility: hidden` rather than `opacity: 0` alone: it takes
             * the pill out of the tab order and out of hit-testing while
             * keeping its box, which is exactly the pair of things wanted.
             */
            className={cn(
              "cta-nudge group inline-flex h-[40px] w-[40px] shrink-0 items-center justify-center overflow-hidden border-2 border-land-cta bg-land-cta text-site-body font-medium text-land-cta-ink hover:border-accent sm:h-[42px] sm:w-auto sm:px-4",
              pastHero
                ? "visible translate-y-0 opacity-100"
                : "pointer-events-none invisible translate-y-1 opacity-0",
            )}
          >
            <span className="hidden whitespace-nowrap sm:inline">Open the dashboard</span>
            <span className="sm:hidden"><Arrow /></span>
            <span className="hidden sm:inline"><Arrow /></span>
          </Link>

          <button
            type="button"
            aria-expanded={mobileOpen}
            aria-controls="mobile-section-navigation"
            aria-label={mobileOpen ? "Close section navigation" : "Open section navigation"}
            onClick={() => setMobileOpen((open) => !open)}
            className="nav-control inline-flex size-10 shrink-0 items-center justify-center border border-land-rule bg-surface text-text-primary transition-colors hover:border-text-muted hover:bg-surface-muted lg:hidden"
          >
            {mobileOpen ? <X className="size-5" aria-hidden /> : <Menu className="size-5" aria-hidden />}
          </button>
        </div>
      </nav>

      <div
        id="mobile-section-navigation"
        aria-hidden={!mobileOpen}
        className={cn(
          "page-shell mt-2 border border-border bg-surface/98 p-2 shadow-[0_20px_45px_-24px_var(--land-nav-shadow)] backdrop-blur-xl transition-[opacity,transform,visibility] duration-200 lg:hidden",
          mobileOpen
            ? "visible translate-y-0 opacity-100"
            : "pointer-events-none invisible -translate-y-2 opacity-0",
        )}
      >
        <ul className="grid grid-cols-2 gap-1" aria-label="Page sections">
          {SECTIONS.map((section) => (
            <li key={section.id}>
              <Link
                href={`#${section.id}`}
                aria-current={active === section.id ? "location" : undefined}
                onClick={() => setMobileOpen(false)}
                className={cn(
                  "flex min-h-11 items-center px-3 py-2 text-site-body text-text-secondary transition-colors hover:bg-surface-muted hover:text-text-primary",
                  active === section.id && "bg-surface-muted text-text-primary",
                )}
              >
                {section.label}
              </Link>
            </li>
          ))}
        </ul>
        <div className="mt-2 grid grid-cols-2 gap-1 border-t border-border pt-2">
          <Link href="/signin" onClick={() => setMobileOpen(false)} className="flex min-h-11 items-center justify-center border border-border-strong px-3 text-site-body font-medium text-text-primary">Sign in</Link>
          <Link href="/dashboard" onClick={() => setMobileOpen(false)} className="flex min-h-11 items-center justify-center bg-land-cta px-3 text-site-body font-medium text-land-cta-ink">Live workspace</Link>
        </div>
      </div>
    </div>
  );
}

export function Arrow() {
  return (
    <svg className="cta-arrow" width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden>
      <path
        d="M2.5 9h12m0 0-4.25-4.25M14.5 9l-4.25 4.25"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
