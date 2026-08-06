import type {
  ApiErrorBody,
  BreakdownResponse,
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
  DatasetProfile,
  DatasetUploadResponse,
  DriverResponse,
  ExportFormat,
  ForecastFrequency,
  ForecastMetricsResponse,
  ForecastPointsResponse,
  ForecastProgressEvent,
  ForecastRun,
  GapFill,
  HealthResponse,
  InsightResponse,
  InsightRewriteResponse,
  LlmCheckResponse,
  LlmRunFields,
  LlmUsageResponse,
  MeasureAggregation,
  OutlierTreatment,
  Scorecard,
  SeriesResponse,
  SeriesSort,
} from "@/types/api";

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
    return this.status === 0 || this.status >= 500 || this.status === 429;
  }
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...init?.headers,
      },
      cache: "no-store",
    });
  } catch (cause) {
    throw new ApiError(
      0,
      "network_error",
      "Could not reach the API. Check that the backend is running.",
      { cause: String(cause) },
    );
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

export const getHealth = () => request<HealthResponse>("/api/health");

export const listConnectors = () => request<Connector[]>("/api/connectors");

export const listConnectorTypes = () => request<ConnectorTypeInfo[]>("/api/connectors/types");

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

export const listConnectorSchemas = (id: string) =>
  request<ConnectorSchemaList>(`/api/connectors/${id}/schemas`);

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
  });

export const listDatasets = () => request<Dataset[]>("/api/datasets");

export const getDataset = (id: string) => request<DatasetDetail>(`/api/datasets/${id}`);

export const getDatasetQuality = (
  id: string,
  params: {
    time_column: string;
    target_column: string;
    frequency: ForecastFrequency;
    aggregation?: MeasureAggregation;
    gap_fill?: GapFill;
  },
) => request<DataQualityResponse>(`/api/datasets/${id}/quality${buildQuery(params)}`);

export const getDatasetProfile = (id: string) =>
  request<DatasetProfile>(`/api/datasets/${id}/profile`);

export async function uploadDataset(file: File, name?: string): Promise<DatasetUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  if (name) form.append("name", name);

  return request<DatasetUploadResponse>("/api/datasets/upload", {
    method: "POST",
    body: form,
  });
}

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

export const listForecastRuns = () => request<ForecastRun[]>("/api/forecasts");

export const getForecastRun = (id: string) => request<ForecastRun>(`/api/forecasts/${id}`);

export const getForecastProgress = (id: string) =>
  request<ForecastProgressEvent>(`/api/forecasts/${id}/progress`);

export const cancelForecastRun = (id: string) =>
  request<ForecastRun>(`/api/forecasts/${id}/cancel`, { method: "POST" });

export const deleteForecastRun = (id: string) =>
  request<void>(`/api/forecasts/${id}`, { method: "DELETE" });

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
} & Partial<LlmRunFields>) =>
  request<ForecastRun>("/api/forecasts/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const getForecastMetrics = (id: string) =>
  request<ForecastMetricsResponse>(`/api/forecasts/${id}/metrics`);

export const getForecastPoints = (
  id: string,
  params: { start?: string; end?: string; series_id?: string } = {},
) => request<ForecastPointsResponse>(`/api/forecasts/${id}/points${buildQuery(params)}`);

export const getForecastSeries = (
  id: string,
  params: {
    sort?: SeriesSort;
    level?: number;
    parent_id?: string;
    search?: string;
    limit?: number;
    offset?: number;
  } = {},
) => request<SeriesResponse>(`/api/forecasts/${id}/series${buildQuery(params)}`);

/** The score already computed, or the reason there is none yet. Never recomputes. */
export const getScorecard = (id: string) => request<Scorecard>(`/api/forecasts/${id}/score`);

/**
 * Grades the forecast against actuals and stores the result.
 *
 * Omitting the dataset uses the newest one that covers the horizon and holds
 * the run's columns, which is what a caller wants in every ordinary case.
 */
export const scoreForecast = (id: string, datasetId?: string) =>
  request<Scorecard>(`/api/forecasts/${id}/score`, {
    method: "POST",
    body: JSON.stringify({ dataset_id: datasetId ?? null }),
  });

export const forecastEventsUrl = (id: string) => `${API_BASE_URL}/api/forecasts/${id}/events`;

export const getSummary = (filters: DashboardFilters) =>
  request<DashboardSummary>(`/api/dashboard/summary${buildQuery(filterParams(filters))}`);

/** The forecast split by one column this run actually has. */
export const getBreakdown = (filters: DashboardFilters, column: string) =>
  request<BreakdownResponse>(
    `/api/dashboard/breakdown${buildQuery({ ...filterParams(filters), column })}`,
  );

export const getDrivers = (filters: DashboardFilters) =>
  request<DriverResponse>(`/api/dashboard/drivers${buildQuery(filterParams(filters))}`);

export const getInsights = (filters: DashboardFilters) =>
  request<InsightResponse>(`/api/insights${buildQuery(filterParams(filters))}`);

/**
 * Re-says the stored insights in the configured model's words.
 *
 * A phrasing pass over a finished run — no model is refitted and no figure can
 * change, so this is what applies a key added after the fact.
 */
export const rewriteInsights = (runId: string | null, llm: LlmRunFields) =>
  request<InsightRewriteResponse>("/api/insights/rewrite", {
    method: "POST",
    body: JSON.stringify({ run_id: runId, ...llm }),
  });

/** Puts the platform's own wording back. */
export const plainInsights = (filters: DashboardFilters) =>
  request<InsightRewriteResponse>(`/api/insights/plain${buildQuery(filterParams(filters))}`, {
    method: "POST",
  });

/** One real request to the provider, so a key can be checked before a run. */
export const checkLlm = (llm: LlmRunFields) =>
  request<LlmCheckResponse>("/api/insights/check", {
    method: "POST",
    body: JSON.stringify(llm),
  });

export const getLlmUsage = (days = 30) =>
  request<LlmUsageResponse>(`/api/usage/llm${buildQuery({ days })}`);

export const exportUrl = (runId: string, format: ExportFormat) =>
  `${API_BASE_URL}/api/exports/${runId}${buildQuery({ format })}`;
