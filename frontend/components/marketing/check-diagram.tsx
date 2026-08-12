const TOTAL = 20;
const HIDDEN = 7;
const SHOWN = TOTAL - HIDDEN;
const HEIGHTS = [22, 30, 26, 38, 33, 44, 36, 48, 41, 52, 46, 58, 50, 61, 54, 66, 57, 70, 62, 74];

const ROWS = [
  { label: "1 · Your sales history", kind: "history" as const },
  { label: "2 · We hide the last few weeks", kind: "hidden" as const },
  { label: "3 · Then compare what we said", kind: "compare" as const },
];

export function CheckDiagram() {
  return (
    <div className="w-full" aria-label="How forecast accuracy is checked against hidden sales history">
      {ROWS.map((row) => (
        <div key={row.label} className="mb-8 last:mb-0">
          <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.17em] text-[#7f8580] sm:text-[13px]">
            {row.label}
          </p>

          <div className="flex h-[92px] items-end gap-1 sm:h-[106px]">
            {HEIGHTS.map((height, index) => {
              const hidden = index >= SHOWN;
              const scaledHeight = `calc(${height}px * 1.28)`;

              if (row.kind === "history" || !hidden) {
                return (
                  <span
                    key={index}
                    style={{ height: scaledHeight }}
                    className="accuracy-bar flex-1 bg-[#d7d8d6]"
                  />
                );
              }

              if (row.kind === "hidden") {
                return (
                  <span
                    key={index}
                    style={{ height: scaledHeight }}
                    className="flex-1 border border-dashed border-[#59605b]/25"
                  />
                );
              }

              const predicted = height * (index % 2 === 0 ? 0.88 : 1.07);
              return (
                <span key={index} className="relative flex flex-1 flex-col justify-end">
                  <span style={{ height: `calc(${predicted}px * 1.28)` }} className="accuracy-bar w-full bg-[#7fbea1]" />
                  <span
                    style={{ bottom: `calc(${height}px * 1.28)` }}
                    className="absolute inset-x-0 h-[2px] bg-[#f0f1ef]"
                  />
                </span>
              );
            })}
          </div>
        </div>
      ))}

      <div className="mt-8 flex flex-wrap items-center gap-x-7 gap-y-3 border-t border-white/10 pt-5 text-[13px] text-[#9ca19d] sm:text-[15px]">
        <span className="flex items-center gap-2.5">
          <span className="inline-block size-3 bg-[#d7d8d6]" aria-hidden />
          Real sales
        </span>
        <span className="flex items-center gap-2.5">
          <span className="inline-block size-3 bg-[#7fbea1]" aria-hidden />
          What we predicted
        </span>
        <span className="flex items-center gap-2.5">
          <span className="inline-block h-[2px] w-5 bg-[#f0f1ef]" aria-hidden />
          What actually happened
        </span>
      </div>
    </div>
  );
}
