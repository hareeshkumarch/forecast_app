"use client";

import { FileSpreadsheet, UploadCloud } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { Button, Field, InlineError, Input } from "@/components/ui/primitives";
import { Select } from "@/components/ui/select";
import { useConfigureDataset, useUploadDataset } from "@/hooks/use-dashboard";
import { errorMessage } from "@/lib/errors";
import { formatBytes, formatInteger } from "@/lib/format";
import { cn } from "@/lib/utils";
import { toast } from "@/stores/toast-store";
import { useUiStore } from "@/stores/ui-store";
import type { DatasetUploadResponse, ForecastFrequency } from "@/types/api";

const FREQUENCIES: { value: ForecastFrequency; label: string }[] = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
  { value: "quarterly", label: "Quarterly" },
];

const MAX_MB = 20;

export function UploadDatasetModal() {
  const modal = useUiStore((state) => state.modal);
  const closeModal = useUiStore((state) => state.closeModal);
  const openModal = useUiStore((state) => state.openModal);
  const open = modal === "upload-dataset";

  const uploadMutation = useUploadDataset();
  const configureMutation = useConfigureDataset();
  const fileInput = useRef<HTMLInputElement>(null);

  const [result, setResult] = useState<DatasetUploadResponse | null>(null);
  const [timeColumn, setTimeColumn] = useState("");
  const [targetColumn, setTargetColumn] = useState("");
  const [frequency, setFrequency] = useState<ForecastFrequency>("monthly");
  const [horizon, setHorizon] = useState(6);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setResult(null);
      setLocalError(null);
      uploadMutation.reset();
      configureMutation.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function handleFile(file: File | undefined) {
    if (!file) return;

    if (file.size > MAX_MB * 1024 * 1024) {
      setLocalError(
        `${file.name} is ${formatBytes(file.size)}, over the ${MAX_MB} MB limit. Filter or aggregate the data first.`,
      );
      return;
    }

    setLocalError(null);
    uploadMutation.mutate(
      { file },
      {
        onSuccess: (response) => {
          setResult(response);
          const profile = response.profile;
          setTimeColumn(
            response.dataset.time_column ?? profile.time_column_suggestions[0]?.name ?? "",
          );
          setTargetColumn(
            response.dataset.target_column ?? profile.target_column_suggestions[0]?.name ?? "",
          );
          setFrequency(profile.detected_frequency ?? "monthly");
          setHorizon(response.dataset.horizon ?? 6);
        },
      },
    );
  }

  function handleConfirm() {
    if (!result) return;
    if (!timeColumn || !targetColumn) {
      setLocalError("Select both a time column and a forecast target.");
      return;
    }
    if (timeColumn === targetColumn) {
      setLocalError("The time column and target column must be different.");
      return;
    }

    configureMutation.mutate(
      {
        id: result.dataset.id,
        time_column: timeColumn,
        target_column: targetColumn,
        frequency,
        horizon,
      },
      {
        onSuccess: (dataset) => {
          toast.success(
            `${dataset.name} is ready`,
            `Forecasting ${dataset.target_column} by ${dataset.time_column}.`,
          );
          closeModal();
          openModal("configure-forecast");
        },
        onError: (error) => setLocalError(errorMessage(error)),
      },
    );
  }

  const profile = result?.profile;
  const failure = localError ?? (uploadMutation.error ? errorMessage(uploadMutation.error) : null);

  return (
    <Modal
      open={open}
      onClose={closeModal}
      title="Upload Dataset"
      description={`CSV or XLSX, up to ${MAX_MB} MB.`}
      size="lg"
      footer={
        result ? (
          <>
            <Button variant="ghost" onClick={closeModal}>
              Cancel
            </Button>
            <Button variant="primary" onClick={handleConfirm} loading={configureMutation.isPending}>
              Continue
            </Button>
          </>
        ) : (
          <Button variant="ghost" onClick={closeModal}>
            Cancel
          </Button>
        )
      }
    >
      {!result ? (
        <div className="space-y-3">
          <FlowSteps current={1} />
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            disabled={uploadMutation.isPending}
            className={cn(
              "flex w-full flex-col items-center justify-center gap-2 rounded-card",
              "border border-dashed border-border-strong bg-surface-muted px-6 py-10",
              "transition-colors duration-fast hover:border-accent hover:bg-accent-soft",
              "disabled:cursor-wait disabled:opacity-70",
            )}
          >
            <UploadCloud className="h-6 w-6 text-text-muted" aria-hidden />
            <span className="text-body font-medium text-text-primary">
              {uploadMutation.isPending ? "Uploading and profiling…" : "Choose a file"}
            </span>
            <span className="text-caption text-text-muted">
              CSV, TSV or XLSX · maximum {MAX_MB} MB
            </span>
          </button>

          <input
            ref={fileInput}
            type="file"
            accept=".csv,.tsv,.txt,.xlsx,.xlsm"
            className="hidden"
            onChange={(event) => handleFile(event.target.files?.[0])}
          />

          <InlineError message={failure ?? undefined} className="px-3 py-2" />
        </div>
      ) : (
        <div className="space-y-4">
          <FlowSteps current={2} />

          <div className="flex items-center gap-2.5 rounded-card border border-border bg-surface-muted px-3 py-2.5">
            <FileSpreadsheet className="h-4 w-4 shrink-0 text-text-secondary" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="truncate text-meta font-medium text-text-primary">
                {result.dataset.original_filename ?? result.dataset.name}
              </p>
              <p className="text-caption text-text-muted">
                {formatInteger(profile?.row_count ?? 0)} rows ·{" "}
                {profile?.column_count ?? 0} columns ·{" "}
                {formatInteger(profile?.missing_value_count ?? 0)} missing (
                {(profile?.missing_value_pct ?? 0).toFixed(2)}%)
                {profile?.date_range_start && profile?.date_range_end
                  ? ` · ${profile.date_range_start} to ${profile.date_range_end}`
                  : ""}
              </p>
            </div>
          </div>

          {(profile?.warnings.length ?? 0) > 0 ? (
            <div className="space-y-1 rounded-card border border-warning-border bg-warning-soft px-3 py-2">
              {profile?.warnings.map((warning) => (
                <p key={warning} className="text-caption text-warning">
                  {warning}
                </p>
              ))}
            </div>
          ) : null}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field
              label="Time column"
              required
              hint={
                profile?.time_column_suggestions[0]
                  ? `Detected: ${profile.time_column_suggestions[0].reason}`
                  : undefined
              }
            >
              <ColumnSelect
                value={timeColumn}
                onChange={setTimeColumn}
                options={(profile?.columns ?? [])
                  .filter((column) => column.is_date_candidate || column.kind === "date")
                  .map((column) => column.name)}
                fallback={(profile?.columns ?? []).map((column) => column.name)}
              />
            </Field>

            <Field label="Forecast target" required>
              <ColumnSelect
                value={targetColumn}
                onChange={setTargetColumn}
                options={(profile?.columns ?? [])
                  .filter((column) => column.is_target_candidate)
                  .map((column) => column.name)}
                fallback={(profile?.columns ?? [])
                  .filter((column) => column.kind === "numeric")
                  .map((column) => column.name)}
              />
            </Field>

            <Field label="Frequency" required>
              <Select value={frequency} onChange={setFrequency} options={FREQUENCIES} />
            </Field>

            <Field label="Horizon (periods)" required>
              <Input
                type="number"
                min={1}
                max={365}
                value={horizon}
                onChange={(event) => setHorizon(Number(event.target.value) || 1)}
              />
            </Field>
          </div>

          {(profile?.preview_rows.length ?? 0) > 0 ? (
            <div>
              <p className="mb-1.5 text-caption font-medium text-text-secondary">Preview</p>
              <div className="scroll-thin max-h-[152px] overflow-auto rounded-card border border-border">
                <table className="w-full border-collapse">
                  <thead className="sticky top-0 bg-surface-muted">
                    <tr>
                      {(profile?.columns ?? []).map((column) => (
                        <th
                          key={column.name}
                          className="table-header whitespace-nowrap px-2.5 py-1.5 text-left font-medium"
                        >
                          {column.name}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(profile?.preview_rows ?? []).slice(0, 6).map((row, index) => (
                      <tr key={index} className="border-t border-border">
                        {(profile?.columns ?? []).map((column) => (
                          <td
                            key={column.name}
                            className="whitespace-nowrap px-2.5 py-1 text-caption text-text-secondary"
                          >
                            {row[column.name] ?? "—"}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          <InlineError message={failure ?? undefined} />
        </div>
      )}
    </Modal>
  );
}

function FlowSteps({ current }: { current: 1 | 2 }) {
  const steps = ["Choose a file", "Map the columns", "Run the forecast"];

  return (
    <ol className="mb-4 flex items-center gap-2">
      {steps.map((label, index) => {
        const step = index + 1;
        const done = step < current;
        const active = step === current;

        return (
          <li key={label} className="flex min-w-0 flex-1 items-center gap-2">
            <span
              className={cn(
                "flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-micro font-semibold",
                done
                  ? "bg-positive text-white"
                  : active
                    ? "bg-accent text-white"
                    : "border border-border bg-surface text-text-muted",
              )}
              aria-hidden
            >
              {step}
            </span>
            <span
              className={cn(
                "truncate text-caption",
                active ? "font-medium text-text-primary" : "text-text-muted",
              )}
            >
              {label}
            </span>
            {step < steps.length ? (
              <span className="hidden h-px flex-1 bg-border sm:block" aria-hidden />
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

function ColumnSelect({
  value,
  onChange,
  options,
  fallback,
}: {
  value: string;
  onChange: (next: string) => void;
  options: string[];
  fallback: string[];
}) {
  const choices = options.length > 0 ? options : fallback;

  return (
    <Select
      value={value}
      onChange={onChange}
      placeholder="Select a column…"
      options={choices.map((name) => ({ value: name, label: name }))}
    />
  );
}
