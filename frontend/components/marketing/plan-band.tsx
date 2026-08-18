import type { CSSProperties } from "react";

import { markDelay } from "@/lib/plan-motion";

const BASE_AT = 0.34;

const COMMIT = { label: "Commit to", value: "18,400", tone: "text-plan-commit" };
const BASE = { label: "Base case", value: "21,900", tone: "text-text-primary" };
const PREPARE = { label: "Be ready for", value: "29,600", tone: "text-plan-prepare" };

type Mark = { label: string; value: string; tone: string };

function Figure({
  mark,
  index,
  className,
  left,
}: {
  mark: Mark;
  index: number;
  className?: string;
  left?: string;
}) {
  return (
    <div
      className={`plan-mark ${className ?? ""}`}
      style={{ "--mark-delay": `${markDelay(index)}ms`, left } as CSSProperties}
    >
      <dt className="whitespace-nowrap font-mono text-site-caption uppercase tracking-[0.13em] text-land-dim">
        {mark.label}
      </dt>
      <dd className={`mt-2 text-stat font-bold leading-none ${mark.tone}`}>{mark.value}</dd>
    </div>
  );
}

export function PlanBand() {
  return (
    <figure className="m-0">
      {/* The base case sits above its own tick rather than in a middle column,
          so the figure and the position it names are the same place. */}
      <dl className="relative grid grid-cols-[auto_1fr_auto] items-start gap-4 sm:block sm:h-[4.5rem]">
        <Figure mark={COMMIT} index={0} className="sm:absolute sm:left-0 sm:top-0" />
        <Figure
          mark={BASE}
          index={1}
          className="justify-self-center text-center sm:absolute sm:top-0 sm:-translate-x-1/2"
          left={`${BASE_AT * 100}%`}
        />
        <Figure mark={PREPARE} index={2} className="text-right sm:absolute sm:right-0 sm:top-0" />
      </dl>

      <div className="relative mt-6 h-14 sm:mt-0">
        <div className="plan-track absolute inset-0 flex">
          <span className="plan-fill-low" style={{ width: `${BASE_AT * 100}%` }} />
          <span className="plan-fill-high flex-1" />
        </div>

        <span aria-hidden className="plan-edge absolute inset-y-0 left-0 w-[3px] bg-plan-commit" />
        <span aria-hidden className="plan-edge absolute inset-y-0 right-0 w-[3px] bg-plan-prepare" />
        <span
          aria-hidden
          className="plan-base absolute inset-y-[-10px] w-[2px] bg-text-primary"
          style={{ left: `${BASE_AT * 100}%` }}
        />
      </div>

      <p className="mt-5 flex justify-between gap-4 font-mono text-site-caption uppercase tracking-[0.12em] text-land-dim">
        <span>9 weeks in 10 clear this</span>
        <span className="text-right">1 week in 10 needs this</span>
      </p>
    </figure>
  );
}
