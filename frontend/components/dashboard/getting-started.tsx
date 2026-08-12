"use client";

import { ArrowRight, Check, Database, PlayCircle, Upload } from "lucide-react";
import { useRouter } from "next/navigation";

import { Button, Card } from "@/components/ui/primitives";
import { PICKER_LIMIT, useDatasets, useForecastRuns } from "@/hooks/use-dashboard";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";

interface Step {
  id: string;
  title: string;
  description: string;
  cta: string;
  icon: typeof Upload;
  done: boolean;
  run: () => void;
}

export function GettingStarted() {
  const openModal = useUiStore((state) => state.openModal);
  const router = useRouter();

  const { data: datasets } = useDatasets({ limit: PICKER_LIMIT });
  const { data: runs } = useForecastRuns({ limit: 1 });

  const hasDataset = (datasets?.total ?? 0) > 0;
  const hasConfiguredDataset = (datasets?.rows ?? []).some(
    (dataset) => dataset.time_column && dataset.target_column,
  );
  const hasRun = (runs?.counts.completed ?? 0) > 0;

  const steps: Step[] = [
    {
      id: "data",
      title: "Bring in some data",
      description: "Upload a CSV or Excel file, or import a table from a connected source.",
      cta: hasDataset ? "Add another" : "Upload a file",
      icon: Upload,
      done: hasDataset,
      run: () => openModal("upload-dataset"),
    },
    {
      id: "map",
      title: "Point at the time and target columns",
      description: "The profiler suggests them; confirm the pair and the reporting frequency.",
      cta: "Review columns",
      icon: Database,
      done: hasConfiguredDataset,
      run: () => (hasDataset ? openModal("configure-forecast") : openModal("upload-dataset")),
    },
    {
      id: "run",
      title: "Run the forecast",
      description:
        "Candidates are fitted, backtested and ranked; the winner fills the dashboard.",
      cta: "Run forecast",
      icon: PlayCircle,
      done: hasRun,
      run: () => openModal("configure-forecast"),
    },
  ];

  const nextStep = steps.find((step) => !step.done) ?? steps[steps.length - 1];

  return (
    <Card className="p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-title font-semibold text-text-primary">Get your first forecast</h3>
          <p className="mt-1 text-meta text-text-secondary">
            Three steps from raw history to a ranked, backtested forecast.
          </p>
        </div>
        <Button variant="ghost" onClick={() => router.push("/connectors")} className="shrink-0">
          Browse connectors
        </Button>
      </div>

      <ol className="mt-4 grid gap-2.5 sm:grid-cols-3">
        {steps.map((step, index) => {
          const Icon = step.icon;
          const isNext = step.id === nextStep?.id && !step.done;

          return (
            <li
              key={step.id}
              className={cn(
                "flex flex-col rounded-card border p-3 transition-colors duration-fast",
                step.done
                  ? "border-positive-border bg-positive-soft/40"
                  : isNext
                    ? "border-accent-border bg-accent-soft"
                    : "border-border bg-surface-muted/40",
              )}
            >
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-caption font-semibold",
                    step.done
                      ? "border-positive-border bg-positive text-white"
                      : "border-border bg-surface text-text-secondary",
                  )}
                  aria-hidden
                >
                  {step.done ? <Check className="h-3.5 w-3.5" /> : index + 1}
                </span>
                <Icon className="h-3.5 w-3.5 shrink-0 text-text-muted" aria-hidden />
              </div>

              <p className="mt-2 text-body font-medium text-text-primary">{step.title}</p>
              <p className="mt-1 flex-1 text-caption text-text-secondary">
                {step.description}
              </p>

              <button
                type="button"
                onClick={step.run}
                className={cn(
                  "mt-2.5 inline-flex items-center gap-1 self-start text-caption font-medium",
                  "transition-colors duration-fast",
                  step.done ? "text-text-muted hover:text-text-secondary" : "text-accent hover:text-accent-hover",
                )}
              >
                {step.cta}
                <ArrowRight className="h-3 w-3" aria-hidden />
              </button>
            </li>
          );
        })}
      </ol>

      <p className="mt-3 text-caption text-text-muted">
        Press <kbd className="rounded-chip border border-border px-1 py-0.5 text-micro">⌘K</kbd> at
        any time for every action.
      </p>
    </Card>
  );
}
