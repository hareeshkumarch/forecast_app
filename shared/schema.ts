import { z } from "zod";

// Column detection result from ML engine
export const columnDetectionSchema = z.object({
  file_id: z.string(),
  filename: z.string(),
  original_filename: z.string().optional(),
  date_col: z.string().nullable(),
  target_col: z.string().nullable(),
  exog_cols: z.array(z.string()),
  all_columns: z.array(z.string()),
  numeric_columns: z.array(z.string()),
  shape: z.array(z.number()),
  preview: z.array(z.record(z.any())),
  // Semantic column mapping intelligence
  mapping_confidence: z.record(z.number()).optional(),
  column_mapping: z.record(z.string()).optional(),
  mapping_suggestions: z.array(z.object({
    col: z.string(),
    role: z.string(),
    confidence: z.number(),
    reason: z.string(),
    is_selected: z.boolean(),
  })).optional(),
  mapping_warnings: z.array(z.string()).optional(),
});

export type ColumnDetection = z.infer<typeof columnDetectionSchema>;


export const forecastConfigSchema = z.object({
  filename: z.string(),
  original_filename: z.string().optional(),
  date_col: z.string(),
  target_col: z.string(),
  exog_cols: z.array(z.string()).default([]),
  frequency: z.string().default("auto"),
  horizon: z.number().min(1).max(365).default(30),
  selected_models: z.array(z.string()).min(1),
  name: z.string().optional(),
  auto_tune: z.boolean().default(false).optional(),
  // FIX Bug 22/34: Added missing fields that frontend sends
  clean_anomalies: z.boolean().default(false).optional(),
  hyperparameters: z.object({
    lstm_epochs: z.number().optional(),
    transformer_epochs: z.number().optional(),
    prophet_cps: z.number().optional(),
    arima_p: z.number().optional(),
    arima_d: z.number().optional(),
    arima_q: z.number().optional(),
  }).optional(),
});

export type ForecastConfig = z.infer<typeof forecastConfigSchema>;

// Model metrics
export const modelMetricsSchema = z.object({
  mae: z.number().nullable().optional(),
  rmse: z.number().nullable().optional(),
  mape: z.number().nullable().optional(),
  r2: z.number().nullable().optional(),
  aic: z.number().nullable().optional(),
  bic: z.number().nullable().optional(),
});

export type ModelMetrics = z.infer<typeof modelMetricsSchema>;

// Demo dataset info
export const demoDatasetSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  rows: z.number(),
  cols: z.number(),
});

export type DemoDataset = z.infer<typeof demoDatasetSchema>;

// Job (from /api/jobs and /api/jobs/:id)
export interface Job {
  id: string;
  name?: string;
  status: string;
  original_filename?: string;
  total_models?: number;
  completed_models?: number;
  selected_models?: string[];
  created_at?: string;
  preprocessing_report?: unknown;
  frequency?: string;
  horizon?: number;
  target_col?: string;
}


// Single forecast point (date + predicted + optional bounds)
export interface ForecastPoint {
  date?: string;
  predicted?: number;
  lower?: number;
  upper?: number;
}

// Single prediction (backtest)
export interface PredictionPoint {
  date?: string;
  actual?: number;
  predicted?: number;
}

// One model result in /api/results/:id
export interface ResultRow {
  model_name: string;
  status: string;
  is_best?: boolean;
  metrics?: ModelMetrics & { mape?: number };
  training_time?: number;
  forecast?: ForecastPoint[];
  predictions?: PredictionPoint[];
  residuals?: number[];
  parameters?: Record<string, unknown>;
  tuning_metrics?: {
    combinations_tested: number;
    selected_params: Record<string, unknown>;
  } | null;
  error?: string;
}

// Full results response
// FIX Bug 35: Added missing fields from job data (name, total_models, horizon, target_col)
export interface ResultsResponse {
  status: string;
  name?: string;
  total_models?: number;
  horizon?: number;
  target_col?: string;
  results?: ResultRow[];
  preprocessing?: {
    statistics?: Record<string, unknown>;
    seasonality?: { detected?: boolean; strength?: number; period?: number };
    stationarity?: { is_stationary?: boolean; p_value?: number };
    warnings?: string[];
  };
}

// Available models
export const AVAILABLE_MODELS = [
  { id: "ARIMA", name: "ARIMA", description: "Auto-Regressive Integrated Moving Average", category: "statistical" },
  { id: "SARIMA", name: "SARIMA", description: "Seasonal ARIMA", category: "statistical" },
  { id: "ARIMAX", name: "ARIMAX", description: "ARIMA with exogenous variables", category: "statistical" },
  { id: "Prophet", name: "Prophet", description: "Facebook's time series forecasting", category: "ml" },
  { id: "Holt-Winters", name: "Holt-Winters", description: "Triple Exponential Smoothing", category: "statistical" },
  { id: "LSTM", name: "LSTM", description: "Long Short-Term Memory neural network", category: "deep_learning" },
  { id: "Transformer", name: "Transformer", description: "Attention-based neural network", category: "deep_learning" },
] as const;
