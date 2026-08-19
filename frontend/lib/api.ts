import type {
  AccuracyReport,
  ApiErrorBody,
  BreakdownResponse,
  CapabilitiesResponse,
  Connector,
  ConnectorSchemaList,
  ConnectorTestResult,
  ConnectorType,
  ConnectorTypeInfo,
  DashboardFilters,
  DashboardSummary,
  DataQualityResponse,
  Dataset,
  DatasetDetail,
  DatasetPage,
  ApiFeatures,
  CoverageResponse,
  DatasetProfile,
  OpenApiDocument,
  DatasetSort,
  DatasetUploadResponse,
  DecisionResponse,
  DriverResponse,
  ExportFormat,
  ForecastFrequency,
  ForecastMetricsResponse,
  ForecastMonitoring,
  ForecastPointsResponse,
  ForecastProgressEvent,
  ForecastRun,
  ForecastRunPage,
  GapFill,
  HealthResponse,
  InsightResponse,
  InsightRewriteResponse,
  LlmCheckResponse,
  LlmRunFields,
  LlmUsageResponse,
  MeasureAggregation,
  ModelKind,
  OutlierTreatment,
  RunSort,
  RunState,
  RunComparison,
  SavedScenario,
  ScenarioSimulation,
  Scorecard,
  SeriesResponse,
  SeriesSort,
  SeriesStatus,
} from "@/types/api";

import { accessToken } from "@/lib/supabase";

export const API_BASE_URL =
  typeof window === "undefined"
    ? process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
    : process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(
    status: number,
    code: string,
    message: string,
    detail: Record<string, unknown>,
    requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.requestId = requestId;
  }

  get isRetryable(): boolean {
    return this.status === 0 || this.status === 408 || this.status === 429 || this.status >= 500;
  }
}

const DEFAULT_TIMEOUT_MS = 30_000;
const LONG_REQUEST_TIMEOUT_MS = 120_000;

function mutationKey(scope: string): string {
  const suffix = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${scope}:${suffix}`;
}

function buildQuery(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

export function filterParams(filters: DashboardFilters): Record<string, string | undefined> {
  return {
    run_id: filters.runId ?? undefined,
    start: filters.start ?? undefined,
    end: filters.end ?? undefined,
    view: filters.view,
  };
}

async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  let response: Response;
  const parentSignal = init?.signal;
  const controller = new AbortController();
  let timedOut = false;

  const abortFromParent = () => controller.abort(parentSignal?.reason);
  if (parentSignal?.aborted) abortFromParent();
  else parentSignal?.addEventListener("abort", abortFromParent, { once: true });

  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const headers = new Headers(init?.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");

  // Every call to the API goes through here, so the session travels with all
  // of them or with none of them. Attaching it per call site is how one gets
  // forgotten and answers 401 in production only.
  const token = await accessToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const hasBody = init?.body !== undefined && init.body !== null;
  if (hasBody && !(init?.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers,
      signal: controller.signal,
      cache: "no-store",
    });
  } catch (cause) {
    if (parentSignal?.aborted) throw cause;
    if (timedOut) {
      throw new ApiError(
        408,
        "request_timeout",
        "The API took too long to respond. Please try again.",
        { timeout_ms: timeoutMs },
      );
    }
    throw new ApiError(
      0,
      "network_error",
      "Could not reach the API. Check that the backend is running.",
      { cause: String(cause) },
    );
  } finally {
    clearTimeout(timeout);
    parentSignal?.removeEventListener("abort", abortFromParent);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  if (!response.ok) {
    let body: ApiErrorBody | null = null;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      body = null;
    }
    throw new ApiError(
      response.status,
      body?.error.code ?? "http_error",
      body?.error.message ?? `The request failed with status ${response.status}.`,
      body?.error.detail ?? {},
      body?.error.request_id ?? response.headers.get("X-Request-ID"),
    );
  }

  return (await response.json()) as T;
}

export const getHealth = (signal?: AbortSignal) =>
  request<HealthResponse>("/api/health", { signal });

export const getCapabilities = (signal?: AbortSignal) =>
  request<CapabilitiesResponse>("/api/health/capabilities", { signal });

export const listConnectors = (signal?: AbortSignal) =>
  request<Connector[]>("/api/connectors", { signal });

export const listConnectorTypes = (signal?: AbortSignal) =>
  request<ConnectorTypeInfo[]>("/api/connectors/types", { signal });

export const createConnector = (payload: {
  name: string;
  type: ConnectorType;
  config: Record<string, unknown>;
  credentials: Record<string, string>;
}) =>
  request<Connector>("/api/connectors", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const updateConnector = (
  id: string,
  payload: {
    name?: string;
    config?: Record<string, unknown>;
    credentials?: Record<string, string>;
  },
) =>
  request<Connector>(`/api/connectors/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const deleteConnector = (id: string) =>
  request<void>(`/api/connectors/${id}`, { method: "DELETE" });

export const testConnector = (payload: {
  connector_id?: string;
  type?: ConnectorType;
  config?: Record<string, unknown>;
  credentials?: Record<string, string>;
}) =>
  request<ConnectorTestResult>("/api/connectors/test", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const listConnectorSchemas = (id: string, signal?: AbortSignal) =>
  request<ConnectorSchemaList>(`/api/connectors/${id}/schemas`, { signal });

export const importFromConnector = (
  id: string,
  payload: {
    schema_name?: string | null;
    table_name?: string | null;
    query?: string | null;
    dataset_name?: string | null;
    row_limit?: number;
  },
) =>
  request<Dataset>(`/api/connectors/${id}/import`, {
    method: "POST",
    body: JSON.stringify(payload),
  }, LONG_REQUEST_TIMEOUT_MS);

export interface DatasetQuery {
  search?: string;
  sort?: DatasetSort;
  limit?: number;
  offset?: number;
}

export const listDatasets = (query: DatasetQuery = {}, signal?: AbortSignal) =>
  request<DatasetPage>(`/api/datasets${buildQuery({ ...query })}`, { signal });

export const getDataset = (id: string, signal?: AbortSignal) =>
  request<DatasetDetail>(`/api/datasets/${id}`, { signal });

export const getDatasetQuality = (
  id: string,
  params: {
    time_column: string;
    target_column: string;
    frequency: ForecastFrequency;
    aggregation?: MeasureAggregation;
    gap_fill?: GapFill;
  },
  signal?: AbortSignal,
) => request<DataQualityResponse>(`/api/datasets/${id}/quality${buildQuery(params)}`, { signal });

export const getDatasetProfile = (id: string, signal?: AbortSignal) =>
  request<DatasetProfile>(`/api/datasets/${id}/profile`, { signal });

/**
 * What the backend actually serves, read from its own OpenAPI document.
 *
 * The frontend deploys from a push and the backend from a command on the box,
 * so for a window after every release one is newer than the other. Most of
 * that mismatch is harmless — a missing endpoint 404s and says so. The one
 * that is not is a query parameter the older backend has never heard of:
 * FastAPI ignores undeclared parameters rather than rejecting them, so a
 * filter the user set is dropped in transit and the answer comes back looking
 * like a filtered one. Asking first is the only way not to lie about it.
 *
 * The spec is ~128KB, so it is reduced to booleans here and only those reach
 * the query cache.
 */
export const getApiFeatures = async (signal?: AbortSignal): Promise<ApiFeatures> => {
  const spec = await request<OpenApiDocument>("/openapi.json", { signal });
  const paths = spec.paths ?? {};
  const seriesParams = paths["/api/forecasts/{run_id}/series"]?.get?.parameters ?? [];

  return {
    seriesStatusFilter: seriesParams.some((parameter) => parameter.name === "status"),
    datasetCoverage: "/api/datasets/{dataset_id}/coverage" in paths,
  };
};

export const getDatasetCoverage = (
  id: string,
  params: { max_series?: number; max_periods?: number } = {},
  signal?: AbortSignal,
) => request<CoverageResponse>(`/api/datasets/${id}/coverage${buildQuery(params)}`, { signal });

export type DateOrder = "auto" | "day_first" | "month_first";

export async function uploadDataset(
  file: File,
  name?: string,
  dateOrder: DateOrder = "auto",
): Promise<DatasetUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  if (name) form.append("name", name);
  // 01/02/2024 is the first of February in most of the world and the second of
  // January in the United States, and a file where no day passes the 12th
  // cannot settle it. "auto" lets the column decide and say when it could not.
  form.append("date_order", dateOrder);

  return request<DatasetUploadResponse>("/api/datasets/upload", {
    method: "POST",
    body: form,
  }, LONG_REQUEST_TIMEOUT_MS);
}

export const deleteDataset = (id: string) =>
  request<void>(`/api/datasets/${id}`, { method: "DELETE" });

export const configureDataset = (
  id: string,
  payload: {
    time_column: string;
    target_column: string;
    frequency: ForecastFrequency;
    horizon: number;
    name?: string;
  },
) =>
  request<DatasetDetail>(`/api/datasets/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export interface RunQuery {
  search?: string;
  state?: RunState;
  sort?: RunSort;
  limit?: number;
  offset?: number;
}

export const listForecastRuns = (query: RunQuery = {}, signal?: AbortSignal) =>
  request<ForecastRunPage>(`/api/forecasts${buildQuery({ ...query })}`, { signal });

export const getForecastRun = (id: string, signal?: AbortSignal) =>
  request<ForecastRun>(`/api/forecasts/${id}`, { signal });

export const getForecastProgress = (id: string, signal?: AbortSignal) =>
  request<ForecastProgressEvent>(`/api/forecasts/${id}/progress`, { signal });

export const cancelForecastRun = (id: string) =>
  request<ForecastRun>(`/api/forecasts/${id}/cancel`, { method: "POST" });

export const deleteForecastRun = (id: string) =>
  request<void>(`/api/forecasts/${id}`, { method: "DELETE" });

export const retryForecastRun = (id: string) =>
  request<ForecastRun>(`/api/forecasts/${id}/retry`, {
    method: "POST",
    headers: { "Idempotency-Key": mutationKey(`retry:${id}`) },
  });

export const startForecast = (payload: {
  dataset_id: string;
  name?: string;
  time_column?: string | null;
  target_column?: string | null;
  weight_column?: string | null;
  region_column?: string | null;
  category_column?: string | null;
  group_by?: string[];
  frequency?: ForecastFrequency | null;
  horizon?: number | null;
  confidence_level?: number;
  aggregation?: MeasureAggregation;
  gap_fill?: GapFill;
  outlier_treatment?: OutlierTreatment;
  max_folds?: number | null;
  max_series?: number | null;
  metric_weights?: Record<string, number> | null;
  sarimax_order?: number[] | null;
  gbm_max_depth?: number | null;
  candidate_models?: ModelKind[] | null;
  prophet_changepoint_prior_scale?: number | null;
  prophet_interval_width?: number | null;
  outlier_mad_threshold?: number | null;
  complexity_penalty_scale?: number | null;
  driver_columns?: string[] | null;
} & Partial<LlmRunFields>) =>
  request<ForecastRun>("/api/forecasts/run", {
    method: "POST",
    headers: { "Idempotency-Key": mutationKey("forecast") },
    body: JSON.stringify(payload),
  });

export const getForecastMetrics = (id: string, signal?: AbortSignal) =>
  request<ForecastMetricsResponse>(`/api/forecasts/${id}/metrics`, { signal });

export const getForecastPoints = (
  id: string,
  params: { start?: string; end?: string; series_id?: string } = {},
  signal?: AbortSignal,
) => request<ForecastPointsResponse>(`/api/forecasts/${id}/points${buildQuery(params)}`, { signal });

export const getForecastSeries = (
  id: string,
  params: {
    sort?: SeriesSort;
    level?: number;
    parent_id?: string;
    search?: string;
    status?: SeriesStatus;
    limit?: number;
    offset?: number;
  } = {},
  signal?: AbortSignal,
) => request<SeriesResponse>(`/api/forecasts/${id}/series${buildQuery(params)}`, { signal });

export const getScorecard = (id: string, signal?: AbortSignal) =>
  request<Scorecard>(`/api/forecasts/${id}/score`, { signal });

export const scoreForecast = (id: string, datasetId?: string) =>
  request<Scorecard>(`/api/forecasts/${id}/score`, {
    method: "POST",
    body: JSON.stringify({ dataset_id: datasetId ?? null }),
  });

export const simulateScenario = (
  id: string,
  payload: {
    volume_multiplier: number;
    target_shift_pct: number;
    driver_multipliers?: Record<string, number>;
  },
) => request<ScenarioSimulation>(`/api/forecasts/${id}/simulate`, {
  method: "POST",
  body: JSON.stringify(payload),
}, LONG_REQUEST_TIMEOUT_MS);

export const listSavedScenarios = (id: string, signal?: AbortSignal) =>
  request<SavedScenario[]>(`/api/forecasts/${id}/scenarios`, { signal });

export const saveScenario = (
  id: string,
  payload: {
    name: string;
    description?: string | null;
    volume_multiplier: number;
    target_shift_pct: number;
    driver_multipliers?: Record<string, number>;
  },
) => request<SavedScenario>(`/api/forecasts/${id}/scenarios`, {
  method: "POST",
  body: JSON.stringify(payload),
}, LONG_REQUEST_TIMEOUT_MS);

export const deleteSavedScenario = (runId: string, scenarioId: string) =>
  request<void>(`/api/forecasts/${runId}/scenarios/${scenarioId}`, { method: "DELETE" });

export const compareForecastRuns = (
  leftRunId: string,
  rightRunId: string,
  signal?: AbortSignal,
) => request<RunComparison>(
  `/api/forecasts/compare${buildQuery({
    left_run_id: leftRunId,
    right_run_id: rightRunId,
  })}`,
  { signal },
);

export const getForecastMonitoring = (signal?: AbortSignal) =>
  request<ForecastMonitoring>("/api/forecasts/monitoring", { signal });

/**
 * The progress stream's URL, with the session on it.
 *
 * The token rides in the query string because `EventSource` cannot set
 * headers — it is the one place in this client that does so, and the backend
 * accepts it there for this endpoint alone. The cost is real: a query string
 * reaches access logs, where an Authorization header does not. It is bounded
 * by Supabase tokens being short-lived, and by this stream carrying only a
 * percentage and a stage name.
 */
export function forecastEventsUrl(id: string, token?: string | null): string {
  const base = `${API_BASE_URL}/api/forecasts/${id}/events`;
  return token ? `${base}?access_token=${encodeURIComponent(token)}` : base;
}

export const getSummary = (filters: DashboardFilters, signal?: AbortSignal) =>
  request<DashboardSummary>(`/api/dashboard/summary${buildQuery(filterParams(filters))}`, { signal });

export const getBreakdown = (filters: DashboardFilters, column: string, signal?: AbortSignal) =>
  request<BreakdownResponse>(
    `/api/dashboard/breakdown${buildQuery({ ...filterParams(filters), column })}`,
    { signal },
  );

export const getDrivers = (filters: DashboardFilters, signal?: AbortSignal) =>
  request<DriverResponse>(`/api/dashboard/drivers${buildQuery(filterParams(filters))}`, { signal });

export const getDecision = (filters: DashboardFilters, signal?: AbortSignal) =>
  request<DecisionResponse>(`/api/dashboard/decision${buildQuery(filterParams(filters))}`, {
    signal,
  });

export const getAccuracyReport = (runId: string, signal?: AbortSignal) =>
  request<AccuracyReport>(`/api/forecasts/${runId}/accuracy`, { signal });

export const getInsights = (filters: DashboardFilters, signal?: AbortSignal) =>
  request<InsightResponse>(`/api/insights${buildQuery(filterParams(filters))}`, { signal });

export const rewriteInsights = (runId: string | null, llm: LlmRunFields) =>
  request<InsightRewriteResponse>("/api/insights/rewrite", {
    method: "POST",
    body: JSON.stringify({ run_id: runId, ...llm }),
  });

export const plainInsights = (filters: DashboardFilters) =>
  request<InsightRewriteResponse>(`/api/insights/plain${buildQuery(filterParams(filters))}`, {
    method: "POST",
  });

export const checkLlm = (llm: LlmRunFields) =>
  request<LlmCheckResponse>("/api/insights/check", {
    method: "POST",
    body: JSON.stringify(llm),
  });

export const getLlmUsage = (days = 30, signal?: AbortSignal) =>
  request<LlmUsageResponse>(`/api/usage/llm${buildQuery({ days })}`, { signal });

export const exportUrl = (runId: string, format: ExportFormat) =>
  `${API_BASE_URL}/api/exports/${runId}${buildQuery({ format })}`;
