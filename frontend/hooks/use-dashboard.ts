"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as api from "@/lib/api";
import { ApiError } from "@/lib/api";
import { toast } from "@/stores/toast-store";
import { useDashboardFilters } from "@/stores/ui-store";
import type {
  DashboardFilters,
  ExportFormat,
  ForecastFrequency,
  GapFill,
  MeasureAggregation,
} from "@/types/api";


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
  runPoints: (id: string, start?: string | null, end?: string | null) =>
    ["forecasts", id, "points", start ?? null, end ?? null] as const,
  summary: (f: DashboardFilters) => ["dashboard", "summary", filterKey(f)] as const,
  regions: (f: DashboardFilters) => ["dashboard", "regions", filterKey(f)] as const,
  categories: (f: DashboardFilters) => ["dashboard", "categories", filterKey(f)] as const,
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

export function useRegions() {
  const filters = useDashboardFilters();
  return useQuery({
    queryKey: queryKeys.regions(filters),
    queryFn: () => api.getRegions(filters),
  });
}

export function useCategories() {
  const filters = useDashboardFilters();
  return useQuery({
    queryKey: queryKeys.categories(filters),
    queryFn: () => api.getCategories(filters),
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


export function useForecastRuns() {
  return useQuery({ queryKey: queryKeys.runs, queryFn: api.listForecastRuns });
}

export function useLlmUsage(days = 30) {
  return useQuery({
    queryKey: queryKeys.llmUsage(days),
    queryFn: () => api.getLlmUsage(days),
    refetchInterval: 30_000,
  });
}


export function useForecastPoints(runId: string | null | undefined) {
  const filters = useDashboardFilters();
  return useQuery({
    queryKey: queryKeys.runPoints(runId ?? "none", filters.start, filters.end),
    queryFn: () =>
      api.getForecastPoints(runId as string, {
        ...(filters.start ? { start: filters.start } : {}),
        ...(filters.end ? { end: filters.end } : {}),
      }),
    enabled: Boolean(runId),
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
    onError: (error: ApiError) => toast.error("Could not save the connector", error.message),
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
    onError: (error: ApiError) => toast.error("Import failed", error.message),
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
    onError: (error: ApiError) => toast.error("Upload failed", error.message),
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
    onError: (error: ApiError) => toast.error("Could not start the forecast", error.message),
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
