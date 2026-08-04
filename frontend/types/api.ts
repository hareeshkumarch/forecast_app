

export type ConnectorType =
  | "postgresql"
  | "mysql"
  | "sqlserver"
  | "csv"
  | "excel"
  | "rest_api"
  | "bigquery"
  | "snowflake"
  | "redshift"
  | "google_sheets"
  | "salesforce";

export type ConnectorStatus = "not_configured" | "configured" | "connected" | "error";

export type ForecastFrequency = "daily" | "weekly" | "monthly" | "quarterly";

export type RunStatus = "pending" | "running" | "completed" | "failed";

export type ModelKind =
  | "naive"
  | "seasonal_naive"
  | "holt_winters"
  | "ets"
  | "theta"
  | "croston"
  | "sarimax"
  | "prophet"
  | "gradient_boosting"
  | "ensemble";

export type PointKind = "actual" | "fitted" | "forecast";

export type InsightSeverity = "positive" | "info" | "warning" | "critical";

export type InsightType =
  | "accuracy_change"
  | "forecast_gap"
  | "regional_growth"
  | "category_decline"
  | "anomaly"
  | "confidence_widening"
  | "worst_case_risk"
  | "driver_positive"
  | "driver_negative"
  | "recommendation";

export type ForecastView = "base" | "best" | "worst";

export type ExportFormat = "csv" | "xlsx" | "json";

export type MeasureAggregation = "sum" | "mean" | "median" | "last" | "min" | "max";

export type GapFill = "auto" | "interpolate" | "zero" | "none";

export type OutlierTreatment = "none" | "winsorise";

export type IssueSeverity = "info" | "warning" | "severe";


export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    detail: Record<string, unknown>;
    request_id?: string;
  };
}


export interface Connector {
  id: string;
  name: string;
  type: ConnectorType;
  status: ConnectorStatus;
  config: Record<string, unknown>;
  last_tested_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  
  credential_keys: string[];
  supports_import: boolean;
}

export interface ConnectorFormField {
  key: string;
  label: string;
  secret: boolean;
  required: boolean;
  kind: "text" | "password" | "number" | "textarea" | "checkbox";
  placeholder: string;
  help_text: string;
}

export interface ConnectorTypeInfo {
  type: ConnectorType;
  display_name: string;
  supports_import: boolean;
  default_port: number | null;
  fields: ConnectorFormField[];
}

export interface ConnectorTestResult {
  ok: boolean;
  status: ConnectorStatus;
  message: string;
  latency_ms: number | null;
  server_version: string | null;
}

export interface SchemaColumn {
  name: string;
  data_type: string;
  nullable: boolean;
}

export interface SchemaTable {
  schema_name: string;
  table_name: string;
  row_estimate: number | null;
  columns: SchemaColumn[];
}

export interface ConnectorSchemaList {
  connector_id: string;
  tables: SchemaTable[];
}


export interface DatasetColumn {
  id: string;
  name: string;
  position: number;
  kind: "date" | "numeric" | "categorical" | "boolean" | "text";
  role: "time" | "target" | "dimension" | "measure" | "weight" | "ignored";
  dtype: string;
  null_count: number;
  distinct_count: number;
  min_value: string | null;
  max_value: string | null;
  mean_value: number | null;
  sample_values: unknown[];
  is_date_candidate: boolean;
  is_target_candidate: boolean;
}

export interface Dataset {
  id: string;
  name: string;
  original_filename: string | null;
  source_kind: string;
  connector_id: string | null;
  status: "uploaded" | "profiling" | "ready" | "failed";
  file_size_bytes: number;
  row_count: number;
  column_count: number;
  missing_value_count: number;
  date_range_start: string | null;
  date_range_end: string | null;
  time_column: string | null;
  target_column: string | null;
  frequency: ForecastFrequency | null;
  horizon: number | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface DatasetDetail extends Dataset {
  columns: DatasetColumn[];
}

export interface ColumnSuggestion {
  name: string;
  kind: DatasetColumn["kind"];
  confidence: number;
  reason: string;
}

export interface DatasetProfile {
  dataset_id: string;
  row_count: number;
  column_count: number;
  missing_value_count: number;
  missing_value_pct: number;
  date_range_start: string | null;
  date_range_end: string | null;
  detected_frequency: ForecastFrequency | null;
  columns: DatasetColumn[];
  time_column_suggestions: ColumnSuggestion[];
  target_column_suggestions: ColumnSuggestion[];
  dimension_suggestions: ColumnSuggestion[];
  preview_rows: Record<string, string | null>[];
  warnings: string[];
}

export interface DatasetUploadResponse {
  dataset: DatasetDetail;
  profile: DatasetProfile;
}


export interface ForecastRun {
  id: string;
  dataset_id: string;
  name: string;
  status: RunStatus;
  progress: number;
  stage: string;
  time_column: string;
  target_column: string;
  weight_column: string | null;
  region_column: string | null;
  category_column: string | null;
  frequency: ForecastFrequency;
  horizon: number;
  confidence_level: number;
  selected_model: ModelKind | null;
  selection_rationale: string | null;
  used_fallback: boolean;
  fallback_reason: string | null;
  history_start: string | null;
  history_end: string | null;
  forecast_start: string | null;
  forecast_end: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  created_at: string;
}

export interface ModelCandidate {
  id: string;
  model: ModelKind;
  rank: number;
  selected: boolean;
  mae: number | null;
  rmse: number | null;
  smape: number | null;
  wmape: number | null;
  score: number | null;
  folds: number;
  fit_seconds: number | null;
  params: Record<string, unknown>;
  failed: boolean;
  failure_reason: string | null;
}

export interface ForecastMetric {
  name: string;
  value: number;
  unit: string;
  previous_value: number | null;
}

export interface ForecastMetricsResponse {
  run_id: string;
  selected_model: ModelKind | null;
  selection_rationale: string | null;
  scoring_rule: string;
  metrics: ForecastMetric[];
  candidates: ModelCandidate[];
}

export interface ForecastPoint {
  period: string;
  kind: PointKind;
  actual: number | null;
  forecast: number | null;
  lower_bound: number | null;
  upper_bound: number | null;
  best_case: number | null;
  base_case: number | null;
  worst_case: number | null;
}

export interface ForecastPointsResponse {
  run_id: string;
  frequency: ForecastFrequency;
  confidence_level: number;
  
  boundary_index: number | null;
  points: ForecastPoint[];
}

export interface ForecastProgressEvent {
  run_id: string;
  status: RunStatus;
  progress: number;
  stage: string;
  message: string | null;
  selected_model: ModelKind | null;
  error: string | null;
}


export interface KpiCard {
  key: string;
  label: string;
  value: number;
  display_value: string;
  unit: string;
  comparison_value: number | null;
  comparison_label: string | null;
  delta: number | null;
  delta_display: string | null;
  direction: "up" | "down" | "flat";
  tone: "positive" | "negative" | "neutral";
}

export interface DashboardSummary {
  run_id: string | null;
  dataset_id: string | null;
  run_name: string | null;
  selected_model: ModelKind | null;
  generated_at: string | null;
  range_start: string | null;
  range_end: string | null;
  kpis: KpiCard[];
  has_data: boolean;
}

export interface RegionRow {
  region: string;
  forecast_value: number;
  prior_year_value: number | null;
  change_vs_last_year: number | null;
  accuracy: number | null;
  share: number | null;
}

export interface RegionResponse {
  run_id: string | null;
  rows: RegionRow[];
  total: number;
}

export interface CategoryRow {
  category: string;
  forecast_value: number;
  share: number;
  change_vs_last_year: number | null;
  accuracy: number | null;
  rank: number;
}

export interface CategoryResponse {
  run_id: string | null;
  rows: CategoryRow[];
  total: number;
  total_display: string;
}

export interface DriverRow {
  driver: string;
  impact_value: number;
  impact_pct: number;
  change_vs_last_year: number | null;
  direction: "up" | "down" | "flat";
  trend: number[];
  rank: number;
}

export interface DriverResponse {
  run_id: string | null;
  rows: DriverRow[];
}

export interface Insight {
  id: string;
  run_id: string;
  type: InsightType;
  severity: InsightSeverity;
  title: string;
  explanation: string;
  suggested_action: string;
  metric_name: string;
  metric_value: number;
  metric_unit: string;
  supporting_data: Record<string, unknown>;
  rank: number;
  generated_at: string;
  llm_rewritten: boolean;
}

export interface InsightResponse {
  run_id: string | null;
  items: Insight[];
}

export interface QualityIssue {
  code: string;
  severity: IssueSeverity;
  message: string;
  remedy: string;
  count: number;
}

export interface DataQualityResponse {
  dataset_id: string;
  time_column: string;
  target_column: string;
  frequency: ForecastFrequency;
  aggregation: MeasureAggregation;
  gap_fill: GapFill;

  rows_scanned: number;
  rows_usable: number;
  periods_present: number;
  periods_expected: number;
  coverage: number;
  gap_count: number;
  longest_gap: number;
  duplicate_rows: number;
  partial_periods: number;
  outlier_periods: number;
  negative_periods: number;
  zero_periods: number;
  constant_target: boolean;
  range_start: string | null;
  range_end: string | null;
  fill_applied: GapFill;
  blocked: boolean;
  severity: IssueSeverity;
  issues: QualityIssue[];
}

export interface HealthResponse {
  status: string;
  database: string;
  storage_writable: boolean;
  forecast_workers: number;
  max_upload_mb: number;
  using_default_credential_key: boolean;
  timestamp: string;
}


export interface DashboardFilters {
  runId?: string | null;
  start?: string | null;
  end?: string | null;
  view: ForecastView;
}
