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
import { useDashboardFilters, useUiStore } from "@/stores/ui-store";
import type { DatasetQuery, RunQuery } from "@/lib/api";
import type {
  AccessRole,
  AccessStatus,
  ApiFeatures,
  DashboardFilters,
  ExportFormat,
  ForecastFrequency,
  GapFill,
  MeasureAggregation,
  SavedScenario,
  SeriesSort,
  SeriesStatus,
} from "@/types/api";

export interface SeriesQuery {
  sort: SeriesSort;
  level?: number;
  parentId?: string;
  search?: string;
  status?: SeriesStatus;
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

const queryKeys = {
  health: ["health"] as const,
  capabilities: ["capabilities"] as const,
  apiFeatures: ["api-features"] as const,
  currentUser: ["auth", "me"] as const,
  managedUsers: ["auth", "users"] as const,
  connectors: ["connectors"] as const,
  connectorTypes: ["connectors", "types"] as const,
  connectorSchemas: (id: string) => ["connectors", id, "schemas"] as const,
  datasets: (query: DatasetQuery = {}) => ["datasets", "list", query] as const,
  allDatasets: ["datasets"] as const,
  dataset: (id: string) => ["datasets", id] as const,
  datasetProfile: (id: string) => ["datasets", id, "profile"] as const,
  datasetQuality: (id: string, key: string) => ["datasets", id, "quality", key] as const,
  datasetCoverage: (id: string) => ["datasets", id, "coverage"] as const,
  runs: (query: RunQuery = {}) => ["forecasts", "list", query] as const,
  allRuns: ["forecasts"] as const,
  run: (id: string) => ["forecasts", id] as const,
  runMetrics: (id: string) => ["forecasts", id, "metrics"] as const,
  runPoints: (id: string, start?: string | null, end?: string | null, seriesId?: string | null) =>
    ["forecasts", id, "points", start ?? null, end ?? null, seriesId ?? null] as const,
  runSeries: (id: string, query: SeriesQuery) => ["forecasts", id, "series", query] as const,
  runScore: (id: string) => ["forecasts", id, "score"] as const,
  scenarios: (id: string) => ["forecasts", id, "scenarios"] as const,
  comparison: (left: string, right: string) => ["forecasts", "compare", left, right] as const,
  monitoring: ["forecasts", "monitoring"] as const,
  scenarioDrivers: (id: string) => ["forecasts", id, "scenario-drivers"] as const,
  summary: (f: DashboardFilters) => ["dashboard", "summary", filterKey(f)] as const,
  breakdown: (f: DashboardFilters, column: string) =>
    ["dashboard", "breakdown", column, filterKey(f)] as const,
  drivers: (f: DashboardFilters) => ["dashboard", "drivers", filterKey(f)] as const,
  decision: (f: DashboardFilters) => ["dashboard", "decision", filterKey(f)] as const,
  accuracyReport: (id: string) => ["forecasts", id, "accuracy"] as const,
  insights: (f: DashboardFilters) => ["dashboard", "insights", filterKey(f)] as const,
  llmUsage: (days: number) => ["usage", "llm", days] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => api.getHealth(signal),
    refetchInterval: 60_000,
  });
}

/**
 * Which models this deployment can fit. Effectively static — it only changes
 * when the image is rebuilt — so it is cached hard and never refetched on a
 * window focus, unlike health.
 */
export function useCapabilities() {
  return useQuery({
    queryKey: queryKeys.capabilities,
    queryFn: ({ signal }) => api.getCapabilities(signal),
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

export function useSummary() {
  const filters = useDashboardFilters();
  return useQuery({
    queryKey: queryKeys.summary(filters),
    queryFn: async ({ signal }) => {
      try {
        const summary = await api.getSummary(filters, signal);
        setCurrencySymbol(summary.currency_symbol);
        return summary;
      } catch (error) {
        // A run pinned in session state may have been deleted in another tab
        // or by a teammate. Fall back to the latest run instead of leaving the
        // whole dashboard stuck on a recoverable 404.
        if (error instanceof ApiError && error.status === 404 && filters.runId) {
          useUiStore.getState().setRunId(null);
        }
        throw error;
      }
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
    queryFn: ({ signal }) => api.getBreakdown(filters, column as string, signal),
    enabled: Boolean(column),
    placeholderData: keepPreviousData,
  });
}

export function useDrivers() {
  const filters = useDashboardFilters();
  return useQuery({
    queryKey: queryKeys.drivers(filters),
    queryFn: ({ signal }) => api.getDrivers(filters, signal),
  });
}

export function useDecision() {
  const filters = useDashboardFilters();
  return useQuery({
    queryKey: queryKeys.decision(filters),
    queryFn: ({ signal }) => api.getDecision(filters, signal),
  });
}

export function useAccuracyReport(runId: string | null) {
  return useQuery({
    queryKey: queryKeys.accuracyReport(runId ?? "none"),
    queryFn: ({ signal }) => api.getAccuracyReport(runId as string, signal),
    enabled: Boolean(runId),
  });
}

export function useInsights() {
  const filters = useDashboardFilters();
  return useQuery({
    queryKey: queryKeys.insights(filters),
    queryFn: ({ signal }) => api.getInsights(filters, signal),
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
    queryFn: ({ signal }) => api.listForecastRuns(query, signal),

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
    queryFn: ({ signal }) => api.getLlmUsage(days, signal),
    refetchInterval: 30_000,

    placeholderData: keepPreviousData,
  });
}

export function useForecastPoints(runId: string | null | undefined, seriesId?: string | null) {
  const filters = useDashboardFilters();
  return useQuery({
    queryKey: queryKeys.runPoints(runId ?? "none", filters.start, filters.end, seriesId),
    queryFn: ({ signal }) =>
      api.getForecastPoints(runId as string, {
        ...(filters.start ? { start: filters.start } : {}),
        ...(filters.end ? { end: filters.end } : {}),
        ...(seriesId ? { series_id: seriesId } : {}),
      }, signal),
    enabled: Boolean(runId),

    placeholderData: keepPreviousData,
  });
}

export function useForecastSeries(runId: string | null | undefined, query: SeriesQuery) {
  return useQuery({
    queryKey: queryKeys.runSeries(runId ?? "none", query),
    queryFn: ({ signal }) =>
      api.getForecastSeries(runId as string, {
        sort: query.sort,
        limit: query.limit,
        offset: query.offset,
        ...(query.level === undefined ? {} : { level: query.level }),
        ...(query.parentId ? { parent_id: query.parentId } : {}),
        ...(query.search ? { search: query.search } : {}),
        ...(query.status ? { status: query.status } : {}),
      }, signal),
    enabled: Boolean(runId),
    placeholderData: keepPreviousData,
  });
}

/**
 * Which of this frontend's features the deployed backend can actually serve.
 *
 * Optimistic when it cannot tell: a probe that fails is not a reason to take
 * away controls that probably work. Matched versions are the normal case, and
 * this only earns its place in the window where they are not.
 */
/**
 * What the backend says about this session, including whether it has been
 * approved. Asked of the server rather than read off the token, because the
 * token proves identity and says nothing about admission.
 */
export function useCurrentUser() {
  return useQuery({
    queryKey: queryKeys.currentUser,
    queryFn: ({ signal }) => api.getCurrentUser(signal),
    staleTime: 60_000,
    retry: false,
    // Somebody waiting for approval has no way to learn it happened: the
    // decision is made on another person's screen, and nothing reaches theirs.
    // Without this they sit on the waiting card until they think to reload,
    // which is exactly the moment the product feels broken. Polled only while
    // they are waiting, and stopped the moment they are through.
    refetchInterval: (query) => (query.state.data?.status === "pending" ? 10_000 : false),
    refetchOnWindowFocus: true,
  });
}

export function useManagedUsers(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.managedUsers,
    queryFn: ({ signal }) => api.getManagedUsers(signal),
    enabled,
    // A request arrives while the administrator is looking at this list, and
    // the list is the place they were told to look. It only runs while the
    // page is open and only for an administrator, so the cost is a small
    // query every twenty seconds by one person.
    refetchInterval: 20_000,
    refetchOnWindowFocus: true,
  });
}

export function useUserDecision() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: AccessStatus }) =>
      api.decideOnUser(id, status),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.managedUsers });
      void client.invalidateQueries({ queryKey: queryKeys.currentUser });
    },
  });
}

export function useUserRole() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, role }: { id: string; role: AccessRole }) => api.setUserRole(id, role),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.managedUsers });
      void client.invalidateQueries({ queryKey: queryKeys.currentUser });
    },
  });
}

export function useBulkDecision() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ ids, status }: { ids: string[]; status: AccessStatus }) =>
      api.decideOnMany(ids, status),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.managedUsers }),
  });
}

export function useBulkRemove() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (ids: string[]) => api.removeMany(ids),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.managedUsers }),
  });
}

export function useRemovePerson() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.removePerson(id),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.managedUsers }),
  });
}

export function useInvite() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (email: string) => api.invitePerson(email),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.managedUsers }),
  });
}

export function useApiFeatures(): ApiFeatures {
  const { data } = useQuery({
    queryKey: queryKeys.apiFeatures,
    queryFn: ({ signal }) => api.getApiFeatures(signal),
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
    retry: 1,
  });

  return data ?? { seriesStatusFilter: true, datasetCoverage: true };
}

export function useDatasetCoverage(datasetId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.datasetCoverage(datasetId ?? "none"),
    queryFn: ({ signal }) => api.getDatasetCoverage(datasetId as string, {}, signal),
    enabled: Boolean(datasetId),
  });
}

export function useScorecard(runId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.runScore(runId ?? "none"),
    queryFn: ({ signal }) => api.getScorecard(runId as string, signal),
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
    queryFn: ({ signal }) => api.getForecastMetrics(runId as string, signal),
    enabled: Boolean(runId),
  });
}

export function useDatasets(query: DatasetQuery = {}) {
  return useQuery({
    queryKey: queryKeys.datasets(query),
    queryFn: ({ signal }) => api.listDatasets(query, signal),
    placeholderData: keepPreviousData,
  });
}

export function useDatasetProfile(id: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.datasetProfile(id ?? "none"),
    queryFn: ({ signal }) => api.getDatasetProfile(id as string, signal),
    enabled: Boolean(id),
  });
}

export function useDataset(id: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.dataset(id ?? "none"),
    queryFn: ({ signal }) => api.getDataset(id as string, signal),
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
    queryFn: ({ signal }) =>
      api.getDatasetQuality(id as string, {
        time_column: params.time_column as string,
        target_column: params.target_column as string,
        frequency: params.frequency,
        aggregation: params.aggregation,
        gap_fill: params.gap_fill,
      }, signal),
    enabled: ready,
    retry: false,
  });
}

export function useConnectors() {
  return useQuery({
    queryKey: queryKeys.connectors,
    queryFn: ({ signal }) => api.listConnectors(signal),
  });
}

export function useSavedScenarios(runId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.scenarios(runId ?? "none"),
    queryFn: ({ signal }) => api.listSavedScenarios(runId as string, signal),
    enabled: Boolean(runId),
  });
}

export function useScenarioDrivers(runId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.scenarioDrivers(runId ?? "none"),
    queryFn: ({ signal }) => api.getDrivers({
      runId: runId as string,
      start: null,
      end: null,
      view: "base",
    }, signal),
    enabled: Boolean(runId),
  });
}

export function useSimulateScenario() {
  return useMutation({
    mutationFn: ({ runId, ...payload }: {
      runId: string;
      volume_multiplier: number;
      target_shift_pct: number;
      driver_multipliers?: Record<string, number>;
    }) => api.simulateScenario(runId, payload),
    onError: (error: unknown) => toast.error("Could not simulate the scenario", errorMessage(error)),
  });
}

export function useSaveScenario() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, ...payload }: {
      runId: string;
      name: string;
      description?: string | null;
      volume_multiplier: number;
      target_shift_pct: number;
      driver_multipliers?: Record<string, number>;
    }) => api.saveScenario(runId, payload),
    onSuccess: (scenario) => {
      client.setQueryData<SavedScenario[]>(queryKeys.scenarios(scenario.run_id), (current) => [
        scenario,
        ...(current ?? []).filter((item) => item.id !== scenario.id),
      ]);
      void client.invalidateQueries({ queryKey: queryKeys.scenarios(scenario.run_id) });
      toast.success("Scenario saved", `${scenario.name} is ready to compare and revisit.`);
    },
    onError: (error: unknown) => toast.error("Could not save the scenario", errorMessage(error)),
  });
}

export function useDeleteSavedScenario() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, scenarioId }: { runId: string; scenarioId: string }) =>
      api.deleteSavedScenario(runId, scenarioId),
    onSuccess: (_result, variables) => {
      client.setQueryData<SavedScenario[]>(queryKeys.scenarios(variables.runId), (current) =>
        current?.filter((scenario) => scenario.id !== variables.scenarioId) ?? [],
      );
      void client.invalidateQueries({ queryKey: queryKeys.scenarios(variables.runId) });
      toast.success("Scenario removed");
    },
    onError: (error: unknown) => toast.error("Could not remove the scenario", errorMessage(error)),
  });
}

export function useRunComparison(leftRunId: string | null, rightRunId: string | null) {
  return useQuery({
    queryKey: queryKeys.comparison(leftRunId ?? "none", rightRunId ?? "none"),
    queryFn: ({ signal }) => api.compareForecastRuns(leftRunId as string, rightRunId as string, signal),
    enabled: Boolean(leftRunId && rightRunId && leftRunId !== rightRunId),
  });
}

export function useForecastMonitoring() {
  return useQuery({
    queryKey: queryKeys.monitoring,
    queryFn: ({ signal }) => api.getForecastMonitoring(signal),
    refetchInterval: 30_000,
    refetchOnWindowFocus: "always",
  });
}

export function useRetryForecastRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.retryForecastRun,
    onSuccess: (run) => {
      void client.invalidateQueries({ queryKey: queryKeys.allRuns });
      void client.invalidateQueries({ queryKey: queryKeys.monitoring });
      toast.info("Retry started", `${run.name} is queued with the original configuration.`);
    },
    onError: (error: unknown) => toast.error("Could not retry the forecast", errorMessage(error)),
  });
}

export function useConnectorTypes() {
  return useQuery({
    queryKey: queryKeys.connectorTypes,
    queryFn: ({ signal }) => api.listConnectorTypes(signal),

    staleTime: Infinity,
  });
}

export function useConnectorSchemas(id: string | null) {
  return useQuery({
    queryKey: queryKeys.connectorSchemas(id ?? "none"),
    queryFn: ({ signal }) => api.listConnectorSchemas(id as string, signal),
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
    mutationFn: ({
      file,
      name,
      dateOrder,
    }: {
      file: File;
      name?: string;
      dateOrder?: api.DateOrder;
    }) => api.uploadDataset(file, name, dateOrder),
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
