import type {
  ApiErrorBody,
  CategoryResponse,
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
  ForecastRun,
  GapFill,
  HealthResponse,
  InsightResponse,
  LlmUsageResponse,
  MeasureAggregation,
  OutlierTreatment,
  RegionResponse,
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

export const getConnector = (id: string) => request<Connector>(`/api/connectors/${id}`);

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

export const startForecast = (payload: {
  dataset_id: string;
  name?: string;
  time_column?: string | null;
  target_column?: string | null;
  weight_column?: string | null;
  region_column?: string | null;
  category_column?: string | null;
  frequency?: ForecastFrequency | null;
  horizon?: number | null;
  confidence_level?: number;
  aggregation?: MeasureAggregation;
  gap_fill?: GapFill;
  outlier_treatment?: OutlierTreatment;
  max_folds?: number | null;
  metric_weights?: Record<string, number> | null;
  sarimax_order?: number[] | null;
  gbm_max_depth?: number | null;
  llm_provider?: string | null;
  llm_api_key?: string | null;
  llm_model?: string | null;
  llm_base_url?: string | null;
  llm_input_cost_per_million?: number | null;
  llm_output_cost_per_million?: number | null;
}) =>
  request<ForecastRun>("/api/forecasts/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const getForecastMetrics = (id: string) =>
  request<ForecastMetricsResponse>(`/api/forecasts/${id}/metrics`);

export const getForecastPoints = (id: string, params: { start?: string; end?: string } = {}) =>
  request<ForecastPointsResponse>(`/api/forecasts/${id}/points${buildQuery(params)}`);

export const forecastEventsUrl = (id: string) => `${API_BASE_URL}/api/forecasts/${id}/events`;

export const getSummary = (filters: DashboardFilters) =>
  request<DashboardSummary>(`/api/dashboard/summary${buildQuery(filterParams(filters))}`);

export const getRegions = (filters: DashboardFilters) =>
  request<RegionResponse>(`/api/dashboard/regions${buildQuery(filterParams(filters))}`);

export const getCategories = (filters: DashboardFilters) =>
  request<CategoryResponse>(`/api/dashboard/categories${buildQuery(filterParams(filters))}`);

export const getDrivers = (filters: DashboardFilters) =>
  request<DriverResponse>(`/api/dashboard/drivers${buildQuery(filterParams(filters))}`);

export const getInsights = (filters: DashboardFilters) =>
  request<InsightResponse>(`/api/insights${buildQuery(filterParams(filters))}`);

export const getLlmUsage = (days = 30) =>
  request<LlmUsageResponse>(`/api/usage/llm${buildQuery({ days })}`);

export const exportUrl = (runId: string, format: ExportFormat) =>
  `${API_BASE_URL}/api/exports/${runId}${buildQuery({ format })}`;
