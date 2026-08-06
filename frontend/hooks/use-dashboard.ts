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
import { setCurrencySymbol } from "@/lib/format";
import { llmRunFields, loadLlmConfig, type LlmConfig } from "@/lib/llm-config";
import { toast } from "@/stores/toast-store";
import { useDashboardFilters } from "@/stores/ui-store";
import type { DatasetQuery, RunQuery } from "@/lib/api";
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
  datasets: (query: DatasetQuery = {}) => ["datasets", "list", query] as const,
  allDatasets: ["datasets"] as const,
  dataset: (id: string) => ["datasets", id] as const,
  datasetProfile: (id: string) => ["datasets", id, "profile"] as const,
  datasetQuality: (id: string, key: string) => ["datasets", id, "quality", key] as const,
  runs: (query: RunQuery = {}) => ["forecasts", "list", query] as const,
  allRuns: ["forecasts"] as const,
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
    queryFn: async () => {
      const summary = await api.getSummary(filters);

      setCurrencySymbol(summary.currency_symbol);
      return summary;
    },
  });
}

const LIVE_PREFIXES = new Set(["dashboard", "forecasts"]);

export function useDashboardRefresh() {
  const refresh = useRefreshDashboard();
  const inFlight = useIsFetching({
    predicate: (query) => LIVE_PREFIXES.has(String(query.queryKey[0])),
  });

  const { dataUpdatedAt } = useSummary();

  return { isFetching: inFlight > 0, updatedAt: dataUpdatedAt, refresh };
}

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

export function useCheckLlm() {
  return useMutation({
    mutationFn: (config: LlmConfig) => api.checkLlm(llmRunFields(config)),
    onError: (error: unknown) => toast.error("Could not reach the provider", errorMessage(error)),
  });
}

const ACTIVE_RUN_POLL_MS = 2_000;

export const PICKER_LIMIT = 50;

export function useForecastRuns(query: RunQuery = {}) {
  return useQuery({
    queryKey: queryKeys.runs(query),
    queryFn: () => api.listForecastRuns(query),

    refetchInterval: (result) => {
      const counts = result.state.data?.counts;
      return counts && counts.active > 0 ? ACTIVE_RUN_POLL_MS : false;
    },
    refetchOnWindowFocus: "always",
    placeholderData: keepPreviousData,
  });
}

export function useLlmUsage(days = 30) {
  return useQuery({
    queryKey: queryKeys.llmUsage(days),
    queryFn: () => api.getLlmUsage(days),
    refetchInterval: 30_000,

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

    placeholderData: keepPreviousData,
  });
}

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

export function useScorecard(runId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.runScore(runId ?? "none"),
    queryFn: () => api.getScorecard(runId as string),
    enabled: Boolean(runId),
  });
}

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

export function useDatasets(query: DatasetQuery = {}) {
  return useQuery({
    queryKey: queryKeys.datasets(query),
    queryFn: () => api.listDatasets(query),
    placeholderData: keepPreviousData,
  });
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

export function useUpdateConnector() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...payload }: { id: string } & Parameters<typeof api.updateConnector>[1]) =>
      api.updateConnector(id, payload),
    onSuccess: (connector) => {
      toast.success(`${connector.name} updated`, "Test it to confirm the new details work.");
      void client.invalidateQueries({ queryKey: queryKeys.connectors });
    },
    onError: (error: unknown) => toast.error("Could not update the connector", errorMessage(error)),
  });
}

export function useDeleteConnector() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.deleteConnector,
    onSuccess: () => {
      toast.success("Connector removed", "Data already imported through it is untouched.");
      void client.invalidateQueries({ queryKey: queryKeys.connectors });
    },
    onError: (error: unknown) => toast.error("Could not remove the connector", errorMessage(error)),
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
      void client.invalidateQueries({ queryKey: queryKeys.allDatasets });
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
      void client.invalidateQueries({ queryKey: queryKeys.allDatasets });
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
      void client.invalidateQueries({ queryKey: queryKeys.allDatasets });
      void client.invalidateQueries({ queryKey: queryKeys.dataset(dataset.id) });
    },
  });
}

export function useDeleteDataset() {
  const client = useQueryClient();

  return useMutation({
    mutationFn: api.deleteDataset,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.allDatasets });
      void client.invalidateQueries({ queryKey: queryKeys.allRuns });
      void client.invalidateQueries({ queryKey: ["forecasts"] });
      void client.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success("File removed", "The upload and anything forecast from it were deleted.");
    },
    onError: (error: unknown) => toast.error("Could not remove the file", errorMessage(error)),
  });
}

export function useStartForecast() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.startForecast,
    onSuccess: (run) => {
      toast.info("Forecast started", `${run.name} is fitting and backtesting candidates.`);
      void client.invalidateQueries({ queryKey: queryKeys.allRuns });
    },
    onError: (error: unknown) => toast.error("Could not start the forecast", errorMessage(error)),
  });
}

export function useDeleteForecastRun() {
  const client = useQueryClient();

  return useMutation({
    mutationFn: api.deleteForecastRun,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.allRuns });
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
      void client.invalidateQueries({ queryKey: queryKeys.allRuns });
      void client.invalidateQueries({ queryKey: queryKeys.run(run.id) });
    },
    onError: (error: unknown) => toast.error("Could not cancel the forecast", errorMessage(error)),
  });
}

export function useRefreshDashboard() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["dashboard"] });
    void client.invalidateQueries({ queryKey: queryKeys.allRuns });
    void client.invalidateQueries({ queryKey: ["forecasts"] });
  };
}

export function downloadExport(runId: string, format: ExportFormat): void {
  window.location.href = api.exportUrl(runId, format);
}

export { ApiError };
