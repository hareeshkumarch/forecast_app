"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Mark } from "@/components/marketing/mark";
import { cn } from "@/lib/utils";

const SECTIONS = [
  { id: "how-it-works", label: "How it works" },
  { id: "features", label: "Features" },
  { id: "compare", label: "Compare" },
  { id: "accuracy", label: "Accuracy" },
];

export function FloatingNav() {
  const [lifted, setLifted] = useState(false);
  const [pastHero, setPastHero] = useState(false);
  const [active, setActive] = useState<string | null>(null);
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
    const onScroll = () => {
      setLifted(window.scrollY > 40);
      setPastHero(window.scrollY > 520);
    };

    onScroll();
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
      observer.disconnect();
    };
  }, []);

  return (
    <div className="fixed inset-x-0 top-[var(--nav-inset)] z-50">
      <nav
        aria-label="Sections"
        className={cn(
          "page-shell flex h-[var(--nav-height)] items-center border border-[#d8ddd7] bg-[#fafbf9]/95 px-4 backdrop-blur-xl transition-shadow duration-300 sm:px-5",
          lifted
            ? "shadow-[0_18px_38px_-22px_rgba(17,22,18,.4),0_1px_2px_rgba(17,22,18,.08)]"
            : "shadow-[0_4px_14px_-10px_rgba(17,22,18,.25)]",
        )}
      >
        <Link href="#top" aria-label="Forecast Hub, back to top" className="flex shrink-0 items-center gap-2.5">
          <Mark size={24} />
          <span className="text-site-h3 font-bold text-[#111512]">Forecast Hub</span>
        </Link>

        <ul ref={listRef} className="relative mx-auto hidden items-center gap-0.5 md:flex">
          {/* The indicator slides between items rather than cutting. It marks
              a position, not a quantity, so it is allowed to overshoot. */}
          <span
            aria-hidden
            data-placing={placed.current ? undefined : "true"}
            className="nav-indicator pointer-events-none absolute inset-y-1 left-0 bg-[#e6e9e4]"
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
                aria-current={active === section.id ? "page" : undefined}
                className={cn(
                  "relative inline-flex px-3.5 py-2 text-site-body text-[#3f443f] transition-colors hover:text-[#111512]",
                  active === section.id && "text-[#111512]",
                )}
              >
                {section.label}
              </Link>
            </li>
          ))}
        </ul>

        <Link
          href="/dashboard"
          aria-label="Open the dashboard"
          aria-hidden={!pastHero}
          tabIndex={pastHero ? 0 : -1}
          className={cn(
            "cta-nudge group ml-auto inline-flex h-[38px] shrink-0 items-center gap-2 border-2 border-[#111512] bg-[#111512] px-3.5 text-site-body font-medium text-white hover:border-[#287b59] sm:h-[42px] sm:px-4",
            pastHero ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-1 opacity-0",
          )}
        >
          <span className="hidden sm:inline">Open the dashboard</span>
          <span className="sm:hidden">Open</span>
          <Arrow />
        </Link>
      </nav>
    </div>
  );
}

export function Arrow() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden>
      <path
        d="M2.5 9h12m0 0-4.25-4.25M14.5 9l-4.25 4.25"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="transition-transform duration-300 group-hover:translate-x-0.5"
      />
    </svg>
  );
}
