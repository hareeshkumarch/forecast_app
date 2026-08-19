"use client";

import { Grid3x3 } from "lucide-react";

import { CoverageGrid } from "@/components/charts/coverage-grid";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/modal";
import { useDatasetCoverage } from "@/hooks/use-dashboard";
import type { Dataset } from "@/types/api";

export function CoverageModal({
  dataset,
  onClose,
}: {
  dataset: Dataset | null;
  onClose: () => void;
}) {
  const { data, isPending, isError, error, refetch } = useDatasetCoverage(dataset?.id);

  return (
    <Modal
      open={dataset !== null}
      onClose={onClose}
      title={dataset ? `What ${dataset.name} actually holds` : "Coverage"}
      description="Every series against every period the frequency implies. Ragged starts, mid-history gaps and runs of zeros are the things worth seeing before a run is paid for."
      size="xl"
    >
      {isPending ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, index) => (
            <Skeleton key={index} className="h-4 w-full" />
          ))}
        </div>
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : !data || data.rows.length === 0 ? (
        <EmptyState
          icon={Grid3x3}
          title="Nothing to show yet"
          message="This file has no date and value columns resolved yet, so it has no series to lay out."
        />
      ) : (
        <div className="space-y-3">
          <Summary coverage={data} />
          <div className="scroll-thin max-h-[60vh] overflow-y-auto">
            <CoverageGrid coverage={data} />
          </div>
        </div>
      )}
    </Modal>
  );
}

function Summary({ coverage }: { coverage: NonNullable<ReturnType<typeof useDatasetCoverage>["data"]> }) {
  const short = coverage.rows.filter((row) => row.observations < coverage.required_history).length;
  const patchy = coverage.rows.filter((row) => row.gaps > 0).length;

  const notes = [
    `${coverage.series_total.toLocaleString()} series over ${coverage.periods_total} periods`,
    short > 0
      ? `${short} with less than the ${coverage.required_history} periods a fitted model needs`
      : "every series has enough history to fit",
    patchy > 0 ? `${patchy} with gaps` : "no gaps",
  ];

  return (
    <div className="space-y-1">
      <p className="text-caption text-text-secondary">{notes.join(" · ")}</p>
      {coverage.series_truncated || coverage.periods_truncated ? (
        <p className="text-caption text-text-muted">
          {coverage.series_truncated
            ? `Showing the ${coverage.series_shown} patchiest of ${coverage.series_total.toLocaleString()} series`
            : null}
          {coverage.series_truncated && coverage.periods_truncated ? ", " : null}
          {coverage.periods_truncated
            ? `showing the most recent ${coverage.periods.length} of ${coverage.periods_total} periods`
            : null}
          .
        </p>
      ) : null}
    </div>
  );
}
