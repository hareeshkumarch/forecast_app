"use client";

import { useEffect } from "react";

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, total, rows, settled]);
}

export function pageRange(offset: number, rows: number, total: number): string {
  if (total === 0) return "none";
  if (rows === 0) return `0 of ${total}`;
  return `${offset + 1}–${offset + rows} of ${total}`;
}
