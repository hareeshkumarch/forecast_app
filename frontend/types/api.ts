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
  | "supabase"
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

export type ExportFormat = "csv" | "pdf";

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
  /** How the raw text was read when it was not already the right type. */
  parsed_as?: string | null;
  reason?: string;
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

export type DatasetSort =
  | "newest"
  | "oldest"
  | "name"
  | "name_desc"
  | "rows"
  | "rows_asc"
  | "size"
  | "size_asc";

export interface DatasetPage {
  total: number;
  limit: number;
  offset: number;
  sort: DatasetSort;

  ready: number;
  row_count: number;
  file_size_bytes: number;
  rows: Dataset[];
}

export type IntakeVerdict = "proceed" | "confirm" | "refuse";

export interface IntakeColumnChoice {
  role: "time" | "target";
  chosen: string | null;
  confidence: number;
  runner_up: string | null;
  runner_up_confidence: number;
  margin: number;
  plausible: boolean;
  confident: boolean;
}

export interface IntakeQuestion {
  code: string;
  column: string | null;
  question: string;
  options: string[];
  evidence: string[];
}

export interface IntakeQuarantine {
  code: string;
  reason: string;
  count: number;
  examples: string[];
}

export interface IntakeGatedSeries {
  series: string;
  observations: number;
  required: number;
  reason: string;
}

export interface Intake {
  verdict: IntakeVerdict;
  columns: IntakeColumnChoice[];
  questions: IntakeQuestion[];
  quarantined: IntakeQuarantine[];
  rows_quarantined: number;
  gated_series: IntakeGatedSeries[];
  gated_series_count: number;
  refusals: string[];
}

export interface DatasetDetail extends Dataset {
  columns: DatasetColumn[];
  intake: Intake | Record<string, never>;
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

  max_series: number;
}

export interface DatasetUploadResponse {
  dataset: DatasetDetail;
  profile: DatasetProfile;
  ready_to_forecast: boolean;
  needs_confirmation: boolean;
  questions: IntakeQuestion[];
}

export type RunState = "completed" | "active" | "failed";

export type RunSort = "newest" | "oldest" | "name" | "series";

export interface RunStateCounts {
  all: number;
  completed: number;
  active: number;
  failed: number;
}

export interface ForecastRunPage {
  total: number;
  limit: number;
  offset: number;
  sort: RunSort;

  counts: RunStateCounts;
  rows: ForecastRun[];
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

  group_by: string[];
  series_count: number;
  frequency: ForecastFrequency;
  horizon: number;
  confidence_level: number;
  aggregation: MeasureAggregation;
  gap_fill: GapFill;
  outlier_treatment: OutlierTreatment;
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

  progress_updated_at?: string | null;
  retry_of_run_id?: string | null;

  scored_at: string | null;
  scored_periods: number;
  realized_wmape: number | null;
  realized_bias: number | null;
  realized_coverage: number | null;
  realized_accuracy: number | null;
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

  mase: number | null;

  winkler: number | null;
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

export interface LeadingColumn {
  name: string;
  lag: number;
  direction: string;
}

export interface ForecastMetricsResponse {
  run_id: string;
  selected_model: ModelKind | null;
  selection_rationale: string | null;
  leading_columns: LeadingColumn[];
  frequency: ForecastFrequency;
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

export type SeriesStatus = "forecast" | "estimated" | "pooled" | "blocked";

export type SeriesSort = "value_at_risk" | "wmape" | "forecast_total" | "label";

export interface MetricWithheld {
  name: string;
  reason: string;
}

/** Which metrics this series' own data can carry, and which one leads. */
export interface MetricPlan {
  demand_class: string;
  headline: string;
  ranking: string[];
  reported: string[];
  withheld: MetricWithheld[];
  seasonal_period: number;
  point_forecast_is_meaningful: boolean;
  note: string;
}

export interface Residual {
  period: string;
  actual: number;
  predicted: number;
  residual: number;
}

export interface ResidualBucket {
  start: number;
  end: number;
  count: number;
}

export interface DiagnosticReport {
  run_id: string;
  series_id: string | null;
  frequency: ForecastFrequency;
  plan: MetricPlan;
  /** Keyed by metric name; a withheld metric is absent, never null. */
  scored: Record<string, number | null>;
  residuals: Residual[];
  histogram: ResidualBucket[];
  residual_sigma: number | null;
  caveats: string[];
}

export interface SeriesRow {
  id: string;
  parent_id: string | null;

  level: number;
  key: Record<string, string>;
  label: string;
  status: SeriesStatus;
  blocked_reason: string | null;
  model: ModelKind | null;
  wmape: number | null;

  mase: number | null;
  accuracy: number | null;

  accuracy_measured: boolean;
  folds: number;
  forecast_total: number;

  current_total: number;
  prior_total: number | null;
  share: number | null;

  value_at_risk: number | null;

  change_vs_prior: number | null;

  scored_periods: number;

  realized_wmape: number | null;
  realized_actual_total: number | null;
}

export interface SeriesResponse {
  run_id: string;
  group_by: string[];
  sort: SeriesSort;
  total: number;
  limit: number;
  offset: number;

  currency: boolean;
  rows: SeriesRow[];
  has_more: boolean;
}

export interface SeriesScoreRow {
  series_id: string;
  label: string;
  level: number;
  forecast_total: number;
  actual_total: number | null;
  wmape: number | null;
  scored_periods: number;

  unscored_reason: string | null;

  miss: number | null;
}

export interface Scorecard {
  run_id: string;
  scored_at: string | null;
  source_dataset_id: string | null;
  source_dataset_name: string | null;
  horizon: number;
  scored_periods: number;

  pending_periods: number;
  covered_through: string | null;
  forecast_total: number;
  actual_total: number;
  wmape: number | null;
  mae: number | null;

  bias: number | null;

  coverage: number | null;
  confidence_level: number | null;

  unforecast_keys: number;
  currency: boolean;
  blocked_reason: string | null;
  restated_since_scoring: number;
  series: SeriesScoreRow[];
  scored: boolean;
  accuracy: number | null;

  intervals_held: boolean | null;

  /** Cumulative error in mean absolute deviations: near zero the misses cancel out. */
  tracking_signal: number | null;
  /** True when the run missed the same way every period, or simply missed badly. */
  drifted: boolean;
}

export interface ForecastProgressEvent {
  run_id: string;
  status: RunStatus;
  progress: number;
  stage: string;
  message: string | null;
  selected_model: ModelKind | null;
  error: string | null;
  updated_at?: string;
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

export interface BreakdownRef {
  column: string;

  label: string;

  source: "series" | "region" | "category" | "";

  cardinality: number;
}

export interface BreakdownRow {
  label: string;
  forecast: number;
  share: number;
  prior: number | null;
  change: number | null;
  accuracy: number | null;
  accuracy_measured: boolean;

  actual: number | null;
}

export interface BreakdownResponse {
  run_id: string | null;
  column: string;
  label: string;
  source: string;
  currency: boolean;
  total: number;
  rows: BreakdownRow[];
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

  currency_symbol: string;

  breakdowns: BreakdownRef[];
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

export type DecisionGrade = "plannable" | "directional" | "indicative";

export interface DecisionAction {
  headline: string;
  detail: string;
}

export interface DecisionHorizon {
  periods: number;
  through: string | null;
  covers_run: boolean;
}

export interface DecisionConcentration {
  count: number;
  total: number;
  share: number;
  leaders: string[];
  lopsided: boolean;
}

export interface DecisionResponse {
  run_id: string | null;
  has_decision: boolean;
  grade: DecisionGrade | null;
  meaning: string | null;
  accuracy: number | null;
  confidence_level: number | null;
  commit: number | null;
  base: number | null;
  prepare: number | null;
  spread_pct: number | null;
  commit_display: string | null;
  base_display: string | null;
  prepare_display: string | null;
  exposure: number | null;
  downside_pct: number | null;
  lean_pct: number | null;
  horizon: DecisionHorizon | null;
  concentration: DecisionConcentration | null;
  actions: DecisionAction[];
}

export interface HorizonAccuracy {
  horizon: number;
  wape: number | null;
  bias_pct: number | null;
  observations: number;
}

export interface ClassAccuracy {
  demand_class: string;
  wape: number | null;
  bias_pct: number | null;
  series: number;
  point_forecast_claimed: boolean;
}

export interface CoveragePoint {
  nominal: number;
  horizon: number;
  observed: number;
  gap_pp: number;
  n_observations: number;
  measurable: boolean;
  holds: boolean;
}

export interface ValueAdd {
  model: string;
  model_error: number | null;
  baseline: string | null;
  baseline_error: number | null;
  improvement_pct: number | null;
  beats_baseline: boolean;
}

export interface AccuracyReport {
  run_id: string;
  dataset_id: string;
  scored_at: string | null;
  measured_against_outcomes: boolean;
  backtest: Record<string, number | null>;
  by_horizon: HorizonAccuracy[];
  by_class: ClassAccuracy[];
  coverage: CoveragePoint[];
  coverage_tolerance_pp: number;
  forecast_value_add: ValueAdd | null;
  caveats: string[];
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

export interface LlmRunFields {
  llm_provider: string | null;
  llm_api_key: string | null;
  llm_model: string | null;
  llm_base_url: string | null;
  llm_input_cost_per_million: number | null;
  llm_output_cost_per_million: number | null;
}

export interface InsightRewriteResponse {
  run_id: string | null;
  considered: number;
  rewritten: number;
  provider: string;
  model: string;
  summary: string;
  items: Insight[];
}

export interface LlmCheckResponse {
  ok: boolean;
  provider: string;
  model: string;
  latency_ms: number;
  message: string;
  error_code: string | null;
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
  database_target: "supabase" | "local";
  database_host: string;
  supabase_configured: boolean;
  storage_writable: boolean;
  forecast_workers: number;
  max_upload_mb: number;
  using_default_credential_key: boolean;
  environment: "development" | "test" | "production";
  database_fallback_enabled: boolean;
  queued_forecast_runs: number;
  running_forecast_runs: number;
  failed_forecast_runs: number;
  /** Model kinds this deployment cannot fit. Empty on a complete install. */
  unavailable_models: ModelKind[];
  timestamp: string;
}

export interface ModelCapability {
  model: ModelKind;
  label: string;
  available: boolean;
  /** Set only when `available` is false, and written to be shown to a user. */
  reason: string | null;
}

export interface CapabilitiesResponse {
  models: ModelCapability[];
  unavailable_models: ModelKind[];
}

export interface ScenarioPoint {
  period: string;
  baseline_forecast: number;
  simulated_forecast: number;
  simulated_lower_bound: number | null;
  simulated_upper_bound: number | null;
  simulated_best_case: number | null;
  simulated_worst_case: number | null;
  delta: number;
  delta_pct: number;
}

export interface ScenarioSimulation {
  run_id: string;
  volume_multiplier: number;
  target_shift_pct: number;
  driver_multipliers: Record<string, number>;
  baseline_total: number;
  simulated_total: number;
  total_delta: number;
  total_delta_pct: number;
  simulated_best_case_total: number;
  simulated_worst_case_total: number;
  method: string;
  intervention_size: number;
  points: ScenarioPoint[];
}

export interface SavedScenario {
  id: string;
  run_id: string;
  name: string;
  description: string | null;
  volume_multiplier: number;
  target_shift_pct: number;
  driver_multipliers: Record<string, number>;
  result: ScenarioSimulation;
  created_at: string;
  updated_at: string;
}

export interface RunComparisonSnapshot {
  run_id: string;
  name: string;
  dataset_id: string;
  model: ModelKind | null;
  frequency: ForecastFrequency;
  horizon: number;
  confidence_level: number;
  forecast_total: number;
  realized_accuracy: number | null;
  realized_wmape: number | null;
  realized_bias: number | null;
  realized_coverage: number | null;
  created_at: string;
}

export interface RunMetricComparison {
  name: string;
  unit: string;
  left: number | null;
  right: number | null;
  delta: number | null;
  delta_pct: number | null;
}

export interface RunComparison {
  left: RunComparisonSnapshot;
  right: RunComparisonSnapshot;
  forecast_total_delta: number;
  forecast_total_delta_pct: number | null;
  metrics: RunMetricComparison[];
}

export interface ForecastMonitorItem {
  run_id: string;
  name: string;
  status: RunStatus;
  model: ModelKind | null;
  completed_at: string | null;
  forecast_end: string | null;
  scored_at: string | null;
  scored_periods: number;
  realized_accuracy: number | null;
  realized_wmape: number | null;
  realized_bias: number | null;
  realized_coverage: number | null;
  alert: string | null;
  alert_level: "critical" | "warning" | "info" | null;
  drifted: boolean;
  can_retry: boolean;
}

export interface ForecastMonitoring {
  total: number;
  healthy: number;
  attention: number;
  failed: number;
  active: number;
  drift_wmape_limit: number;
  rows: ForecastMonitorItem[];
}

export interface LlmUsageTotals {
  requests: number;
  successful_requests: number;
  failed_requests: number;
  rejected_requests: number;
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
  cost_usd: number;
  priced_requests: number;
  average_latency_ms: number | null;
  p95_latency_ms: number | null;
}

export interface LlmUsagePoint {
  date: string;
  requests: number;
  successful_requests: number;
  total_tokens: number;
  cost_usd: number;
}

export interface LlmUsageBreakdown {
  provider: string;
  model: string;
  requests: number;
  successful_requests: number;
  total_tokens: number;
  cost_usd: number;
  priced_requests: number;
  average_latency_ms: number | null;
}

export interface LlmUsageEvent {
  id: string;
  run_id: string | null;
  purpose: string;
  insight_type: string | null;
  provider: string;
  model: string;
  status: "success" | "error" | "rejected";
  applied: boolean;
  input_tokens: number | null;
  output_tokens: number | null;
  cached_input_tokens: number | null;
  reasoning_tokens: number | null;
  total_tokens: number | null;
  latency_ms: number | null;
  cost_usd: number | null;
  cost_source: "provider" | "configured" | "unavailable";
  error_code: string | null;
  created_at: string;
}

export interface LlmUsageResponse {
  days: number;
  generated_at: string;
  totals: LlmUsageTotals;
  timeseries: LlmUsagePoint[];
  by_model: LlmUsageBreakdown[];
  recent: LlmUsageEvent[];

  first_event_at: string | null;
}

export interface DashboardFilters {
  runId?: string | null;
  start?: string | null;
  end?: string | null;
  view: ForecastView;
}

export interface CoverageRow {
  series_id: string;
  observations: number;
  gaps: number;
  zeros: number;
  status: "ok" | "warn" | "reject";
  route: "model" | "fallback" | "none";
  /** One entry per period, null where the series has no row for that period. */
  values: (number | null)[];
}

export interface CoverageResponse {
  dataset_id: string;
  frequency: ForecastFrequency;
  periods: string[];
  rows: CoverageRow[];
  series_total: number;
  series_shown: number;
  periods_total: number;
  required_history: number;
  series_truncated: boolean;
  periods_truncated: boolean;
}

export interface OpenApiDocument {
  paths?: Record<string, { get?: { parameters?: { name: string }[] } }>;
}

/** Endpoints and parameters the running backend declares. */
export interface ApiFeatures {
  seriesStatusFilter: boolean;
  datasetCoverage: boolean;
}

export type AccessStatus = "pending" | "approved" | "rejected";

export type AccessRole = "admin" | "member" | "viewer";

export interface CurrentUserRead {
  authenticated: boolean;
  status: AccessStatus | null;
  role: AccessRole | null;
  is_admin: boolean;
  id: string | null;
  email: string | null;
  name: string | null;
  picture: string | null;
}

export interface ManagedUser {
  id: string;
  email: string;
  name: string | null;
  picture: string | null;
  status: AccessStatus;
  role: AccessRole;
  requested_at: string | null;
  decided_at: string | null;
  decided_by: string | null;
  last_seen_at: string | null;
  invited_by: string | null;
  /** True for an invitation nobody has signed in to yet. */
  subject_pending: boolean;
  is_self: boolean;
}
