"use client";

import { Database, FileSpreadsheet, Plus, Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  Skeleton,
} from "@/components/ui/primitives";
import { RefreshButton } from "@/components/ui/refresh-button";
import { SortableHeader, useSortedRows } from "@/components/ui/sortable-header";
import { useDatasets, useDeleteDataset } from "@/hooks/use-dashboard";
import { formatBytes, formatDateRange, formatRelativeTime, humanizeKey } from "@/lib/format";
import { labelGranularity } from "@/lib/periods";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import type { Dataset } from "@/types/api";

type DatasetSortKey = "name" | "row_count" | "created_at" | "file_size_bytes";

const STATUS_TONE: Record<Dataset["status"], "positive" | "warning" | "negative" | "neutral"> = {
  ready: "positive",
  profiling: "warning",
  uploaded: "neutral",
  failed: "negative",
};

/**
 * Everything that has been uploaded, and what can be done with it.
 *
 * There was no such screen. Files went in through a dialog and were never seen
 * again — no way to check what a run was built on, no way to forecast the same
 * data twice without uploading it twice, and no way to remove anything, though
 * the endpoint to do so has been there all along.
 */
export function DatasetsWorkspace() {
  const { data, isLoading, isError, error, refetch, isFetching, dataUpdatedAt } = useDatasets();
  const remove = useDeleteDataset();
  const openModal = useUiStore((state) => state.openModal);
  const [query, setQuery] = useState("");

  const datasets = useMemo(() => data ?? [], [data]);

  const matching = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return datasets;
    return datasets.filter((dataset) =>
      [dataset.name, dataset.original_filename, dataset.target_column, dataset.time_column]
        .filter(Boolean)
        .some((field) => String(field).toLowerCase().includes(needle)),
    );
  }, [datasets, query]);

  const { sorted, sort, toggle } = useSortedRows<Dataset, DatasetSortKey>(
    matching,
    { key: "created_at", direction: "desc" },
    (row, key) => row[key],
  );

  const ready = datasets.filter((dataset) => dataset.status === "ready").length;
  const rows = datasets.reduce((total, dataset) => total + dataset.row_count, 0);
  const bytes = datasets.reduce((total, dataset) => total + dataset.file_size_bytes, 0);

  function handleRemove(dataset: Dataset) {
    const confirmed = window.confirm(
      `Delete "${dataset.name}"? Any forecast built from it is removed too, and the uploaded file is deleted.`,
    );
    if (confirmed) remove.mutate(dataset.id);
  }

  return (
    <main
      id="main-content"
      className="scroll-thin min-w-0 flex-1 overflow-y-auto bg-canvas px-4 py-4 sm:px-6 sm:py-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-heading font-semibold tracking-[-0.015em] text-text-primary">Data</h1>
          <p className="mt-0.5 text-meta text-text-secondary">
            Everything you have uploaded, and what each file holds.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <RefreshButton
            updatedAt={dataUpdatedAt}
            isFetching={isFetching}
            onRefresh={() => void refetch()}
          />
          <Button variant="primary" icon={Plus} onClick={() => openModal("upload-dataset")}>
            Upload data
          </Button>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ["Files", datasets.length.toLocaleString()],
          ["Ready to forecast", ready.toLocaleString()],
          ["Rows held", rows.toLocaleString()],
          ["On disk", formatBytes(bytes)],
        ].map(([label, value]) => (
          <Card key={label} className="p-3.5">
            <p className="text-caption text-text-muted">{label}</p>
            <p className="mt-1 text-kpi font-semibold text-text-primary num">{value}</p>
          </Card>
        ))}
      </div>

      {isLoading ? (
        <div className="mt-4 space-y-2" aria-hidden>
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-12 w-full" />
          ))}
        </div>
      ) : isError ? (
        <Card className="mt-4">
          <ErrorState error={error} onRetry={() => void refetch()} />
        </Card>
      ) : datasets.length === 0 ? (
        <Card className="mt-4">
          <EmptyState
            icon={Database}
            title="Nothing uploaded yet"
            message="A CSV or Excel file with a date column and a number to forecast is all it takes."
            action={
              <Button variant="primary" onClick={() => openModal("upload-dataset")}>
                Upload your first file
              </Button>
            }
          />
        </Card>
      ) : (
        <Card className="mt-4 overflow-hidden">
          <div className="border-b border-border p-3">
            <div className="relative max-w-sm">
              <Search
                className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted"
                aria-hidden
              />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search by name, file or column"
                aria-label="Search data"
                className="pl-8"
              />
            </div>
          </div>

          <div className="scroll-thin relative overflow-x-auto">
            <table className="w-full border-collapse text-meta">
              <thead>
                <tr className="border-b border-border">
                  <SortableHeader label="Name" sortKey="name" sort={sort} onToggle={toggle} />
                  <th scope="col" className="table-header px-3 pb-1.5 text-left font-medium">
                    Forecasting
                  </th>
                  <th scope="col" className="table-header px-3 pb-1.5 text-left font-medium">
                    Covers
                  </th>
                  <SortableHeader
                    label="Rows"
                    sortKey="row_count"
                    sort={sort}
                    onToggle={toggle}
                    align="right"
                    className="text-right"
                  />
                  <SortableHeader
                    label="Size"
                    sortKey="file_size_bytes"
                    sort={sort}
                    onToggle={toggle}
                    align="right"
                    className="text-right"
                  />
                  <SortableHeader
                    label="Uploaded"
                    sortKey="created_at"
                    sort={sort}
                    onToggle={toggle}
                    align="right"
                    className="text-right"
                  />
                  <th scope="col" className="table-header px-3 pb-1.5 text-right font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((dataset) => (
                  <tr
                    key={dataset.id}
                    className="border-b border-border last:border-0 transition-colors duration-fast hover:bg-surface-muted"
                  >
                    <td className="px-3 py-2.5">
                      <div className="flex items-start gap-2">
                        <FileSpreadsheet
                          className="mt-0.5 h-3.5 w-3.5 shrink-0 text-text-muted"
                          aria-hidden
                        />
                        <div className="min-w-0">
                          <p className="truncate font-medium text-text-primary">{dataset.name}</p>
                          {dataset.original_filename ? (
                            <p className="truncate text-caption text-text-muted">
                              {dataset.original_filename}
                            </p>
                          ) : null}
                        </div>
                        {dataset.status !== "ready" ? (
                          <Badge tone={STATUS_TONE[dataset.status]}>
                            {humanizeKey(dataset.status)}
                          </Badge>
                        ) : null}
                      </div>
                    </td>

                    {/* What a run on this file would forecast, without opening it. */}
                    <td className="px-3 py-2.5 text-text-secondary">
                      {dataset.target_column ? (
                        <>
                          <span className="text-text-primary">{dataset.target_column}</span>
                          {dataset.frequency ? (
                            <span className="text-text-muted">
                              {" · "}
                              {humanizeKey(dataset.frequency)}
                            </span>
                          ) : null}
                        </>
                      ) : (
                        <span className="text-text-muted">Not configured</span>
                      )}
                    </td>

                    <td className="px-3 py-2.5 text-text-secondary">
                      {formatDateRange(
                        dataset.date_range_start,
                        dataset.date_range_end,
                        labelGranularity(dataset.frequency),
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-right num text-text-primary">
                      {dataset.row_count.toLocaleString()}
                    </td>
                    <td className="px-3 py-2.5 text-right num text-text-secondary">
                      {formatBytes(dataset.file_size_bytes)}
                    </td>
                    <td className="px-3 py-2.5 text-right text-text-muted">
                      {formatRelativeTime(dataset.created_at)}
                    </td>

                    <td className="px-3 py-2.5">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={Plus}
                          disabled={dataset.status !== "ready"}
                          onClick={() => openModal("configure-forecast", dataset.id)}
                        >
                          Forecast
                        </Button>
                        <button
                          type="button"
                          aria-label={`Delete ${dataset.name}`}
                          onClick={() => handleRemove(dataset)}
                          disabled={remove.isPending}
                          className={cn(
                            "inline-flex h-11 w-11 items-center justify-center rounded-chip fine:h-7 fine:w-7",
                            "text-text-muted transition-colors duration-fast",
                            "hover:bg-negative-soft hover:text-negative",
                            "disabled:pointer-events-none disabled:opacity-50",
                          )}
                        >
                          <Trash2 className="h-3.5 w-3.5" aria-hidden />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {sorted.length === 0 ? (
            <EmptyState
              icon={Search}
              title="Nothing matches that"
              message={`No file mentions "${query.trim()}".`}
            />
          ) : null}
        </Card>
      )}
    </main>
  );
}
