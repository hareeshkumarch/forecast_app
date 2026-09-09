"use client";

import { useEffect } from "react";

/**
 * Puts the reader back on a page that exists.
 *
 * Rows leave underneath a paged list: the last dataset on page three is
 * deleted, a filter narrows eight runs to two, a search is typed. The offset
 * being asked for is then past the end, and the answer is an empty table under
 * a "Previous" button and a count reading "51–50 of 50" — an empty state that
 * is not empty, on a page the reader cannot tell they have left.
 *
 * Only once the answer belongs to the current query. Acting on a page that is
 * still loading, or on the previous query's rows kept for the transition,
 * would send somebody back to the start every time they typed a letter.
 */
export function usePageInRange({
  page,
  pageSize,
  total,
  rows,
  settled,
  onChange,
}: {
  page: number;
  pageSize: number;
  total: number | undefined;
  rows: number;
  settled: boolean;
  onChange: (page: number) => void;
}): void {
  useEffect(() => {
    if (!settled || page === 0 || rows > 0 || total === undefined) return;
    onChange(Math.max(0, Math.ceil(total / pageSize) - 1));
    // `onChange` is a setter from useState in every caller, so it is stable;
    // listing it would re-run this on each render of an inline arrow.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, total, rows, settled]);
}

/** `1–25 of 240`, or an honest nothing when there is nothing on the page. */
export function pageRange(offset: number, rows: number, total: number): string {
  if (total === 0) return "none";
  if (rows === 0) return `0 of ${total}`;
  return `${offset + 1}–${offset + rows} of ${total}`;
}
