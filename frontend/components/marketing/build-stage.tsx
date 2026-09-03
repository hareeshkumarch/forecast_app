import type { CSSProperties } from "react";

import {
  AHEAD,
  COLUMNS,
  ROWS,
  SLOTS,
  SOLD,
  STAGE,
  columnX,
  lift,
  morph,
  rowY,
  slotWidth,
  slotX,
  spread,
} from "@/lib/pipeline";

const MONO = "var(--font-plex-mono), ui-monospace, monospace";

type CellProps = { row: number; column: number };

function cellText({ row, column }: CellProps): string {
  const key = COLUMNS[column]?.key ?? "";
  const values = ROWS[row];
  if (!values) return "";
  return (values as Record<string, string>)[key] ?? "";
}

function textX(column: number): number {
  const definition = COLUMNS[column];
  if (!definition) return 0;
  return definition.align === "end"
    ? columnX(column) + definition.width - 14
    : columnX(column) + 14;
}

/** The band the forecast could move inside, as one closed shape: the upper
 *  edge out and the lower edge back. */
function bandPath(): string {
  const start = SOLD.length;
  const top = AHEAD.map((value, step) => {
    const x = slotX(start + step) + STAGE.barWidth / 2;
    return `${step === 0 ? "M" : "L"}${x.toFixed(1)},${(STAGE.baseline - lift(value * (1 + spread(step)))).toFixed(1)}`;
  }).join(" ");
  const bottom = [...AHEAD]
    .map((value, step) => ({ value, step }))
    .reverse()
    .map(({ value, step }) => {
      const x = slotX(start + step) + STAGE.barWidth / 2;
      return `L${x.toFixed(1)},${(STAGE.baseline - lift(value * (1 - spread(step)))).toFixed(1)}`;
    })
    .join(" ");
  return `${top} ${bottom} Z`;
}

/**
 * Seven rows of a spreadsheet, and the forecast they turn into.
 *
 * Every mark here is drawn once and then moved by CSS off the progress the
 * scroll writes — there is no state, no clock and no re-render, which is what
 * makes a scrub of the whole build cost the same as scrolling past a picture.
 */
export function BuildStage() {
  const valueColumn = COLUMNS.findIndex((column) => column.role === "value");
  const dateColumn = COLUMNS.findIndex((column) => column.role === "date");
  const sheetBottom = rowY(ROWS.length - 1) + STAGE.cellHeight;

  return (
    <svg
      viewBox={`0 0 ${STAGE.width} ${STAGE.height}`}
      className="build-stage"
      role="img"
      aria-label="A spreadsheet of weekly sales, its date and quantity columns picked out, and the quantity column becoming a forecast with a range around it"
    >
      <g className="sheet">
        <g className="sheet-head">
          {COLUMNS.map((column, index) => (
            <text
              key={column.key}
              x={textX(index)}
              y={STAGE.headTop + 20}
              textAnchor={column.align === "end" ? "end" : "start"}
              fontFamily={MONO}
              fontSize="14"
              letterSpacing="0.06em"
              fill="var(--build-head)"
            >
              {column.head}
            </text>
          ))}
          <line
            x1={0}
            y1={STAGE.headTop + STAGE.headHeight}
            x2={STAGE.width}
            y2={STAGE.headTop + STAGE.headHeight}
            stroke="var(--build-rule)"
          />
        </g>

        {ROWS.map((_, row) => (
          <g key={row} className="sheet-row" style={{ "--i": row } as CSSProperties}>
            <line
              x1={0}
              y1={rowY(row) + STAGE.cellHeight}
              x2={STAGE.width}
              y2={rowY(row) + STAGE.cellHeight}
              stroke="var(--build-rule-soft)"
            />
            {COLUMNS.map((column, index) =>
              index === valueColumn ? null : (
                <text
                  key={column.key}
                  x={textX(index)}
                  y={rowY(row) + 20}
                  textAnchor={column.align === "end" ? "end" : "start"}
                  fontFamily={MONO}
                  fontSize="15"
                  fill="var(--build-ink)"
                  className={column.role === "date" ? "sheet-keyed" : "sheet-spare"}
                >
                  {cellText({ row, column: index })}
                </text>
              ),
            )}
          </g>
        ))}

        {/* The two columns the second beat finds. Outlines rather than fills,
            so the values inside them stay the values and do not become a
            highlight to be read past. */}
        {[dateColumn, valueColumn].map((index) => (
          <rect
            key={index}
            className="sheet-pick"
            x={columnX(index) + 2}
            y={STAGE.headTop}
            width={(COLUMNS[index]?.width ?? 0) - 4}
            height={sheetBottom - STAGE.headTop}
            fill="none"
            stroke="var(--accent)"
            strokeWidth="1.5"
          />
        ))}
        <g className="sheet-tag">
          <text
            x={columnX(dateColumn) + 2}
            y={sheetBottom + 20}
            fontFamily={MONO}
            fontSize="14"
            letterSpacing="0.08em"
            fill="var(--accent)"
          >
            date
          </text>
          <text
            x={columnX(valueColumn) + (COLUMNS[valueColumn]?.width ?? 0) - 4}
            y={sheetBottom + 20}
            textAnchor="end"
            fontFamily={MONO}
            fontSize="14"
            letterSpacing="0.08em"
            fill="var(--accent)"
          >
            quantity
          </text>
        </g>
      </g>

      {/* What the third beat draws on. Held back until the bars have somewhere
          to land, or the chart is furniture waiting for its data. */}
      <g className="build-axis">
        <line
          x1={0}
          y1={STAGE.baseline}
          x2={STAGE.width}
          y2={STAGE.baseline}
          stroke="var(--build-rule)"
        />
        <line
          className="build-split"
          x1={slotX(SOLD.length) - (slotWidth() - STAGE.barWidth) / 2}
          y1={STAGE.baseline - STAGE.ceiling - 12}
          x2={slotX(SOLD.length) - (slotWidth() - STAGE.barWidth) / 2}
          y2={STAGE.baseline}
          stroke="var(--build-rule)"
          strokeDasharray="4 5"
        />
        <text
          x={slotX(SOLD.length) - (slotWidth() - STAGE.barWidth) / 2 - 10}
          y={STAGE.baseline + 20}
          textAnchor="end"
          fontFamily={MONO}
          fontSize="14"
          letterSpacing="0.08em"
          fill="var(--build-head)"
        >
          sold
        </text>
        <text
          x={slotX(SOLD.length) - (slotWidth() - STAGE.barWidth) / 2 + 10}
          y={STAGE.baseline + 20}
          fontFamily={MONO}
          fontSize="14"
          letterSpacing="0.08em"
          fill="var(--accent)"
        >
          forecast
        </text>
      </g>

      {/* The quantity column, on its way to being the history. Two rects under
          one transform: the cell it is now fading out from under the bar it is
          becoming, so the change of material happens over the same travel and
          not as a swap at the end of it. */}
      {SOLD.map((value, row) => {
        const shape = morph(row);
        const column = COLUMNS[valueColumn];
        const travel = {
          "--dx": `${shape.dx.toFixed(2)}px`,
          "--dy": `${shape.dy.toFixed(2)}px`,
        };
        return (
          <g
            key={row}
            className="cell-morph"
            style={{ ...travel, "--i": row } as CSSProperties}
          >
            {/*
              The value is a sibling of the cell rather than a child of it.
              `transform-box: fill-box` resolves against the group's own
              bounding box, and a text node travelling inside that group moves
              the box it is being measured against — so the cell's origin
              drifted with it and the bars were thrown clean out of the frame.
            */}
            <g
              className="sheet-cell"
              style={{ "--sx": shape.sx.toFixed(4), "--sy": shape.sy.toFixed(4) } as CSSProperties}
            >
              <rect
                className="cell-face"
                x={columnX(valueColumn)}
                y={rowY(row)}
                width={column?.width ?? 0}
                height={STAGE.cellHeight}
                fill="var(--build-cell)"
              />
              <rect
                className="cell-bar"
                x={columnX(valueColumn)}
                y={rowY(row)}
                width={column?.width ?? 0}
                height={STAGE.cellHeight}
                fill="var(--build-bar)"
              />
            </g>
            <text
              className="cell-value"
              x={textX(valueColumn)}
              y={rowY(row) + 20}
              textAnchor="end"
              fontFamily={MONO}
              fontSize="15"
              fill="var(--build-ink)"
            >
              {value}
            </text>
          </g>
        );
      })}

      <g className="build-ahead">
        <path className="ahead-band" d={bandPath()} fill="var(--accent)" fillOpacity="0.16" />
        {AHEAD.map((value, step) => (
          <rect
            key={step}
            className="ahead-bar"
            x={slotX(SOLD.length + step)}
            y={STAGE.baseline - lift(value)}
            width={STAGE.barWidth}
            height={lift(value)}
            fill="var(--accent)"
            style={{ "--i": step, "--n": AHEAD.length } as CSSProperties}
          />
        ))}
      </g>

      <desc>{`Seven weeks of sales, ${SOLD.join(", ")}, followed by ${AHEAD.length} forecast weeks across ${SLOTS} weeks in total.`}</desc>
    </svg>
  );
}
