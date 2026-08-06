"use client";


import {
  keepPreviousData,
  useIsFetching,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import * as api from "@/lib/api";
import { ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { llmRunFields, loadLlmConfig, type LlmConfig } from "@/lib/llm-config";
import { toast } from "@/stores/toast-store";
import { useDashboardFilters } from "@/stores/ui-store";
import type {
  DashboardFilters,
  ExportFormat,
  ForecastFrequency,
  GapFill,
  MeasureAggregation,
  SeriesSort,
} from "@/types/api";

export interface SeriesQuery {
  sort: SeriesSort;
  level?: number;
  parentId?: string;
  search?: string;
  limit: number;
  offset: number;
}


function filterKey(filters: DashboardFilters) {
  return {
    runId: filters.runId ?? null,
    start: filters.start ?? null,
    end: filters.end ?? null,
    view: filters.view,
  };
}

export const queryKeys = {
  health: ["health"] as const,
  connectors: ["connectors"] as const,
  connectorTypes: ["connectors", "types"] as const,
  connectorSchemas: (id: string) => ["connectors", id, "schemas"] as const,
  datasets: ["datasets"] as const,
  dataset: (id: string) => ["datasets", id] as const,
  datasetProfile: (id: string) => ["datasets", id, "profile"] as const,
  datasetQuality: (id: string, key: string) => ["datasets", id, "quality", key] as const,
  runs: ["forecasts"] as const,
  run: (id: string) => ["forecasts", id] as const,
  runMetrics: (id: string) => ["forecasts", id, "metrics"] as const,
  runPoints: (id: string, start?: string | null, end?: string | null, seriesId?: string | null) =>
    ["forecasts", id, "points", start ?? null, end ?? null, seriesId ?? null] as const,
  runSeries: (id: string, query: SeriesQuery) => ["forecasts", id, "series", query] as const,
  runScore: (id: string) => ["forecasts", id, "score"] as const,
  summary: (f: DashboardFilters) => ["dashboard", "summary", filterKey(f)] as const,
  breakdown: (f: DashboardFilters, column: string) =>
    ["dashboard", "breakdown", column, filterKey(f)] as const,
  drivers: (f: DashboardFilters) => ["dashboard", "drivers", filterKey(f)] as const,
  insights: (f: DashboardFilters) => ["dashboard", "insights", filterKey(f)] as const,
  llmUsage: (days: number) => ["usage", "llm", days] as const,
};


export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: api.getHealth,
    refetchInterval: 60_000,
  });
}


export function useSummary() {
  const filters = useDashboardFilters();
  return useQuery({
    queryKey: queryKeys.summary(filters),
    queryFn: () => api.getSummary(filters),
  });
}

//: What "the dashboard" is, for the purposes of refreshing it.
const LIVE_PREFIXES = new Set(["dashboard", "forecasts"]);

/**
 * The state a refresh control needs: how old the screen is, whether anything
 * is in flight, and how to ask for new numbers.
 *
 * Every panel owns its own query, so one button has to reach across all of
 * them — refreshing the summary alone would leave the chart and the splits
 * showing older figures beside a newer headline. Each panel keeps what it is
 * already drawing until its replacement arrives, so the screen updates in
 * place rather than emptying and refilling.
 */
export function useDashboardRefresh() {
  const refresh = useRefreshDashboard();
  const inFlight = useIsFetching({
    predicate: (query) => LIVE_PREFIXES.has(String(query.queryKey[0])),
  });
  // The summary is the headline every other panel is read against, so its age
  // is the one worth reporting. Sharing a key with the panels means this adds
  // an observer, not a request.
  const { dataUpdatedAt } = useSummary();

  return { isFetching: inFlight > 0, updatedAt: dataUpdatedAt, refresh };
}

/**
 * One split of the forecast. Disabled until a column is known, because the
 * available splits come from the summary and are not knowable up front.
 */
export function useBreakdown(column: string | null) {
  const filters = useDashboardFilters();
  return useQuery({
    queryKey: queryKeys.breakdown(filters, column ?? "none"),
    queryFn: () => api.getBreakdown(filters, column as string),
    enabled: Boolean(column),
    placeholderData: keepPreviousData,
  });
}

export function useDrivers() {
  const filters = useDashboardFilters();
  return useQuery({
    queryKey: queryKeys.drivers(filters),
    queryFn: () => api.getDrivers(filters),
  });
}

export function useInsights() {
  const filters = useDashboardFilters();
  return useQuery({
    queryKey: queryKeys.insights(filters),
    queryFn: () => api.getInsights(filters),
  });
}

/**
 * Re-says the insights on screen in the configured model's words.
 *
 * The alternative was re-running the whole forecast, which refits every
 * candidate model for what is only a phrasing change — so a key added after a
 * run used to be worth nothing until the next one.
 */
export function useRewriteInsights() {
  const client = useQueryClient();
  const filters = useDashboardFilters();

  return useMutation({
    mutationFn: () => api.rewriteInsights(filters.runId ?? null, llmRunFields(loadLlmConfig())),
    onSuccess: (result) => {
      client.setQueryData(queryKeys.insights(filters), {
        run_id: result.run_id,
        items: result.items,
      });
      if (result.rewritten > 0) {
        toast.success("Insights rewritten", result.summary);
      } else {
        toast.info("Insights left as they were", result.summary);
      }
    },
    onError: (error: unknown) =>
      toast.error("Could not rewrite the insights", errorMessage(error)),
  });
}

/** Puts the platform's own wording back, without touching a provider. */
export function usePlainInsights() {
  const client = useQueryClient();
  const filters = useDashboardFilters();

  return useMutation({
    mutationFn: () => api.plainInsights(filters),
    onSuccess: (result) => {
      client.setQueryData(queryKeys.insights(filters), {
        run_id: result.run_id,
        items: result.items,
      });
      toast.success("Back to plain wording", result.summary);
    },
    onError: (error: unknown) => toast.error("Could not restore the wording", errorMessage(error)),
  });
}

/** One real request to the provider, so a key can be checked before a run. */
export function useCheckLlm() {
  return useMutation({
    mutationFn: (config: LlmConfig) => api.checkLlm(llmRunFields(config)),
    onError: (error: unknown) => toast.error("Could not reach the provider", errorMessage(error)),
  });
}


/** A run that has not settled yet; the list has to keep moving while it works. */
const ACTIVE_RUN_POLL_MS = 2_000;

export function useForecastRuns() {
  return useQuery({
    queryKey: queryKeys.runs,
    queryFn: api.listForecastRuns,
    // Runs now finish on a worker, so nothing tells this list they moved.
    // Poll only while something is actually in flight, then go quiet again.
    refetchInterval: (query) => {
      const runs = query.state.data;
      if (!runs) return false;
      const working = runs.some((run) => run.status === "pending" || run.status === "running");
      return working ? ACTIVE_RUN_POLL_MS : false;
    },
    refetchOnWindowFocus: "always",
  });
}

export function useLlmUsage(days = 30) {
  return useQuery({
    queryKey: queryKeys.llmUsage(days),
    queryFn: () => api.getLlmUsage(days),
    refetchInterval: 30_000,
    // Changing the window is a new query key. Without this the whole page
    // drops to skeletons to answer "the same question over 7 days instead of
    // 30", which reads as the screen breaking rather than narrowing.
    placeholderData: keepPreviousData,
  });
}


export function useForecastPoints(runId: string | null | undefined, seriesId?: string | null) {
  const filters = useDashboardFilters();
  return useQuery({
    queryKey: queryKeys.runPoints(runId ?? "none", filters.start, filters.end, seriesId),
    queryFn: () =>
      api.getForecastPoints(runId as string, {
        ...(filters.start ? { start: filters.start } : {}),
        ...(filters.end ? { end: filters.end } : {}),
        ...(seriesId ? { series_id: seriesId } : {}),
      }),
    enabled: Boolean(runId),
    // Picking a different series, or narrowing the dates, keeps the current
    // chart drawn until the new one arrives rather than flashing a skeleton
    // over a picture that was already correct a moment ago.
    placeholderData: keepPreviousData,
  });
}

/**
 * A page of a grouped run's series.
 *
 * The previous page stays on screen while the next one loads — paging a triage
 * list that blanks between pages loses your place every time you move.
 */
export function useForecastSeries(runId: string | null | undefined, query: SeriesQuery) {
  return useQuery({
    queryKey: queryKeys.runSeries(runId ?? "none", query),
    queryFn: () =>
      api.getForecastSeries(runId as string, {
        sort: query.sort,
        limit: query.limit,
        offset: query.offset,
        ...(query.level === undefined ? {} : { level: query.level }),
        ...(query.parentId ? { parent_id: query.parentId } : {}),
        ...(query.search ? { search: query.search } : {}),
      }),
    enabled: Boolean(runId),
    placeholderData: keepPreviousData,
  });
}

/** The score already stored for a run, or the reason there is none yet. */
export function useScorecard(runId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.runScore(runId ?? "none"),
    queryFn: () => api.getScorecard(runId as string),
    enabled: Boolean(runId),
  });
}

/**
 * Grades a run against actuals.
 *
 * Everything the score touches is invalidated on success — the run row carries
 * the realized figures, the series rows carry their own, and the points now
 * have actuals on them.
 */
export function useScoreForecast(runId: string) {
  const client = useQueryClient();

  return useMutation({
    mutationFn: (datasetId?: string) => api.scoreForecast(runId, datasetId),
    onSuccess: (card) => {
      client.setQueryData(queryKeys.runScore(runId), card);
      void client.invalidateQueries({ queryKey: ["forecasts"] });
      toast.success(
        card.scored
          ? `Scored against ${card.source_dataset_name ?? "the latest data"}.`
          : "Nothing to score yet.",
        card.scored
          ? `${card.scored_periods} of ${card.horizon} periods graded.`
          : card.blocked_reason ?? undefined,
      );
    },
    onError: (error: unknown) => toast.error("Could not score this forecast", errorMessage(error)),
  });
}

export function useForecastMetrics(runId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.runMetrics(runId ?? "none"),
    queryFn: () => api.getForecastMetrics(runId as string),
    enabled: Boolean(runId),
  });
}


export function useDatasets() {
  return useQuery({ queryKey: queryKeys.datasets, queryFn: api.listDatasets });
}

export function useDatasetProfile(id: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.datasetProfile(id ?? "none"),
    queryFn: () => api.getDatasetProfile(id as string),
    enabled: Boolean(id),
  });
}

export function useDataset(id: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.dataset(id ?? "none"),
    queryFn: () => api.getDataset(id as string),
    enabled: Boolean(id),
  });
}


export function useDatasetQuality(
  id: string | null,
  params: {
    time_column: string | null;
    target_column: string | null;
    frequency: ForecastFrequency;
    aggregation: MeasureAggregation;
    gap_fill: GapFill;
  },
) {
  const ready = Boolean(id && params.time_column && params.target_column);
  const key = [params.time_column, params.target_column, params.frequency, params.aggregation, params.gap_fill].join("|");

  return useQuery({
    queryKey: queryKeys.datasetQuality(id ?? "none", key),
    queryFn: () =>
      api.getDatasetQuality(id as string, {
        time_column: params.time_column as string,
        target_column: params.target_column as string,
        frequency: params.frequency,
        aggregation: params.aggregation,
        gap_fill: params.gap_fill,
      }),
    enabled: ready,
    retry: false,
  });
}


export function useConnectors() {
  return useQuery({ queryKey: queryKeys.connectors, queryFn: api.listConnectors });
}

export function useConnectorTypes() {
  return useQuery({
    queryKey: queryKeys.connectorTypes,
    queryFn: api.listConnectorTypes,
    
    staleTime: Infinity,
  });
}

export function useConnectorSchemas(id: string | null) {
  return useQuery({
    queryKey: queryKeys.connectorSchemas(id ?? "none"),
    queryFn: () => api.listConnectorSchemas(id as string),
    enabled: Boolean(id),
    retry: false,
  });
}


export function useTestConnector() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.testConnector,


    onSettled: (_data, _error, variables) => {
      if (variables.connector_id) {
        void client.invalidateQueries({ queryKey: queryKeys.connectors });
      }
    },
  });
}

export function useCreateConnector() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.createConnector,
    onSuccess: (connector) => {
      toast.success(`${connector.name} saved`, "Credentials are encrypted before storage.");
      void client.invalidateQueries({ queryKey: queryKeys.connectors });
    },
    onError: (error: unknown) => toast.error("Could not save the connector", errorMessage(error)),
  });
}

export function useImportFromConnector() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...payload }: { id: string } & Parameters<typeof api.importFromConnector>[1]) =>
      api.importFromConnector(id, payload),
    onSuccess: (dataset) => {
      toast.success(
        `Imported ${dataset.name}`,
        `${dataset.row_count.toLocaleString()} rows are ready to forecast.`,
      );
      void client.invalidateQueries({ queryKey: queryKeys.datasets });
      void client.invalidateQueries({ queryKey: queryKeys.connectors });
    },
    onError: (error: unknown) => toast.error("Import failed", errorMessage(error)),
  });
}

export function useUploadDataset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ file, name }: { file: File; name?: string }) => api.uploadDataset(file, name),
    onSuccess: (response) => {
      toast.success(
        "Dataset profiled",
        `${response.profile.row_count.toLocaleString()} rows, ${response.profile.column_count} columns.`,
      );
      void client.invalidateQueries({ queryKey: queryKeys.datasets });
    },
    onError: (error: unknown) => toast.error("Upload failed", errorMessage(error)),
  });
}

export function useConfigureDataset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...payload
    }: {
      id: string;
      time_column: string;
      target_column: string;
      frequency: ForecastFrequency;
      horizon: number;
      name?: string;
    }) => api.configureDataset(id, payload),
    onSuccess: (dataset) => {
      void client.invalidateQueries({ queryKey: queryKeys.datasets });
      void client.invalidateQueries({ queryKey: queryKeys.dataset(dataset.id) });
    },
  });
}

export function useStartForecast() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.startForecast,
    onSuccess: (run) => {
      toast.info("Forecast started", `${run.name} is fitting and backtesting candidates.`);
      void client.invalidateQueries({ queryKey: queryKeys.runs });
    },
    onError: (error: unknown) => toast.error("Could not start the forecast", errorMessage(error)),
  });
}


export function useDeleteForecastRun() {
  const client = useQueryClient();

  return useMutation({
    mutationFn: api.deleteForecastRun,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.runs });
      void client.invalidateQueries({ queryKey: ["dashboard"] });
      void client.invalidateQueries({ queryKey: ["forecasts"] });
      toast.success("Forecast run cleared", "Its stored results and generated exports were removed.");
    },
    onError: (error: unknown) => toast.error("Could not clear the run", errorMessage(error)),
  });
}


export function useCancelForecastRun() {
  const client = useQueryClient();

  return useMutation({
    mutationFn: api.cancelForecastRun,
    onSuccess: (run) => {
      void client.invalidateQueries({ queryKey: queryKeys.runs });
      void client.invalidateQueries({ queryKey: queryKeys.run(run.id) });
    },
    onError: (error: unknown) => toast.error("Could not cancel the forecast", errorMessage(error)),
  });
}


export function useRefreshDashboard() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["dashboard"] });
    void client.invalidateQueries({ queryKey: queryKeys.runs });
    void client.invalidateQueries({ queryKey: ["forecasts"] });
  };
}

export function downloadExport(runId: string, format: ExportFormat): void {
  
  
  window.location.href = api.exportUrl(runId, format);
}

export { ApiError };
