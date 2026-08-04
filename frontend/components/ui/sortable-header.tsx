"use client";

import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { useMemo, useState } from "react";

import { cn } from "@/lib/utils";

export type SortDirection = "asc" | "desc";

export interface SortState<K extends string> {
  key: K;
  direction: SortDirection;
}

/**
 * Sorting for the panel tables. Nulls always sink to the bottom rather than
 * being treated as zero, so a missing accuracy never looks like the worst one.
 */
export function useSortedRows<T, K extends string>(
  rows: T[],
  initial: SortState<K>,
  accessor: (row: T, key: K) => string | number | null | undefined,
) {
  const [sort, setSort] = useState<SortState<K>>(initial);

  const sorted = useMemo(() => {
    const copy = [...rows];
    const factor = sort.direction === "asc" ? 1 : -1;

    copy.sort((left, right) => {
      const a = accessor(left, sort.key);
      const b = accessor(right, sort.key);

      const aMissing = a === null || a === undefined;
      const bMissing = b === null || b === undefined;
      if (aMissing && bMissing) return 0;
      if (aMissing) return 1;
      if (bMissing) return -1;

      if (typeof a === "string" || typeof b === "string") {
        return String(a).localeCompare(String(b)) * factor;
      }
      return (Number(a) - Number(b)) * factor;
    });

    return copy;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, sort]);

  function toggle(key: K) {
    setSort((previous) =>
      previous.key === key
        ? { key, direction: previous.direction === "asc" ? "desc" : "asc" }
        : { key, direction: typeof key === "string" ? "desc" : "desc" },
    );
  }

  return { sorted, sort, toggle };
}

export function SortableHeader<K extends string>({
  label,
  sortKey,
  sort,
  onToggle,
  align = "left",
  className,
}: {
  label: string;
  sortKey: K;
  sort: SortState<K>;
  onToggle: (key: K) => void;
  align?: "left" | "right";
  className?: string;
}) {
  const active = sort.key === sortKey;
  const Icon = !active ? ChevronsUpDown : sort.direction === "asc" ? ArrowUp : ArrowDown;

  return (
    <th
      scope="col"
      aria-sort={active ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}
      className={cn("table-header px-3 pb-1.5 font-medium", className)}
    >
      <button
        type="button"
        onClick={() => onToggle(sortKey)}
        className={cn(
          "inline-flex w-full items-center gap-1 transition-colors duration-fast hover:text-text-secondary",
          align === "right" ? "justify-end" : "justify-start",
          active && "text-text-secondary",
        )}
      >
        {align === "right" ? null : label}
        <Icon
          className={cn("h-3 w-3 shrink-0", active ? "opacity-100" : "opacity-40")}
          aria-hidden
        />
        {align === "right" ? label : null}
      </button>
    </th>
  );
}
