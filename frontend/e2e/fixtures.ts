import type { Page } from "@playwright/test";

/*
 * A dashboard with data in it, served to the browser instead of the API.
 *
 * These are layout tests: they assert how the shell reflows, not what the
 * backend returned. Three of them still needed a *populated* dashboard —
 * `.grid-charts`, the scenario control and the insights toggle only exist once
 * `has_data` is true — so without a seeded backend running they could never
 * pass, whatever the layout did.
 *
 * Stubbing the responses makes the suite say what it means: same layout, same
 * assertions, at four viewports, on any machine. The payloads are deliberately
 * the smallest shape each panel renders from rather than a copy of a real
 * response, so there is less here to drift out of date.
 */

const CORS = {
  // The app calls a different origin, so a fulfilled response needs the
  // headers the real API would have sent or the browser discards it.
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
};

const RUN_ID = "e2e-run";

function kpi(key: string, label: string, display: string) {
  return {
    key,
    label,
    value: 1200,
    display_value: display,
    unit: "currency",
    comparison_value: 1000,
    comparison_label: "vs last period",
    delta: 0.2,
    delta_display: "+20%",
    direction: "up",
    tone: "positive",
  };
}

const SUMMARY = {
  run_id: RUN_ID,
  dataset_id: "e2e-dataset",
  run_name: "E2E run",
  selected_model: "sarimax",
  generated_at: "2026-01-01T00:00:00Z",
  range_start: "2025-01-01",
  range_end: "2026-01-01",
  currency_symbol: "$",
  has_data: true,
  kpis: [
    kpi("total_forecast", "Total Forecast", "$4.82M"),
    kpi("actual_ytd", "Actual YTD", "$3.11M"),
    kpi("accuracy", "Forecast Accuracy", "91.4%"),
    kpi("wmape", "Weighted MAPE", "8.6%"),
    kpi("best_case", "Best Case", "$5.24M"),
    kpi("worst_case", "Worst Case", "$4.31M"),
  ],
  breakdowns: [
    { column: "region", label: "Region", source: "region", cardinality: 3 },
    { column: "category", label: "Category", source: "category", cardinality: 4 },
  ],
};

const BREAKDOWN = {
  run_id: RUN_ID,
  column: "region",
  label: "Region",
  source: "region",
  currency: true,
  total: 4800,
  rows: [
    { label: "EMEA", forecast: 2400, share: 0.5, prior: 2000, actual: 2300 },
    { label: "AMER", forecast: 1600, share: 0.33, prior: 1500, actual: 1550 },
    { label: "APAC", forecast: 800, share: 0.17, prior: 900, actual: 850 },
  ],
};

const DRIVERS = {
  run_id: RUN_ID,
  rows: [
    {
      driver: "Promotions",
      impact_value: 320,
      impact_pct: 0.07,
      change_vs_last_year: 0.03,
      direction: "up",
      trend: [1, 2, 3, 4, 5, 4, 6],
      rank: 1,
    },
    {
      driver: "Price",
      impact_value: -120,
      impact_pct: -0.03,
      change_vs_last_year: -0.01,
      direction: "down",
      trend: [6, 5, 5, 4, 3, 3, 2],
      rank: 2,
    },
  ],
};

const INSIGHTS = {
  run_id: RUN_ID,
  items: [
    {
      id: "insight-1",
      type: "accuracy_change",
      severity: "positive",
      title: "Accuracy improved after the refit",
      explanation: "The error rate fell from 10.4% to 8.6% once a seasonal model took over.",
      metric_value: -1.8,
      metric_unit: "pp",
      llm_rewritten: false,
    },
    {
      id: "insight-2",
      type: "confidence_widening",
      severity: "warning",
      title: "Confidence widening in Frozen",
      explanation: "The interval on Frozen has grown since the last run.",
      metric_value: 2.1,
      metric_unit: "x",
      llm_rewritten: false,
    },
  ],
};

const METRICS = {
  run_id: RUN_ID,
  selected_model: "sarimax",
  selection_rationale: "Best weighted score across five folds.",
  leading_columns: [],
  frequency: "monthly",
  scoring_rule: "balanced",
  metrics: [
    { name: "wmape", value: 8.6, unit: "%", previous_value: 10.4 },
    { name: "smape", value: 9.1, unit: "%", previous_value: 10.9 },
    { name: "rmse", value: 412, unit: "", previous_value: 470 },
  ],
  candidates: [
    {
      id: "candidate-1",
      model: "sarimax",
      rank: 1,
      selected: true,
      mae: 300,
      rmse: 412,
      smape: 9.1,
      wmape: 8.6,
      mase: 0.8,
      winkler: 1200,
      score: 8.8,
      folds: 5,
    },
    {
      id: "candidate-2",
      model: "holt_winters",
      rank: 2,
      selected: false,
      mae: 360,
      rmse: 470,
      smape: 10.9,
      wmape: 10.4,
      mase: 0.95,
      winkler: 1400,
      score: 10.6,
      folds: 5,
    },
  ],
};

const POINTS = {
  run_id: RUN_ID,
  frequency: "monthly",
  confidence_level: 0.8,
  boundary_index: 5,
  points: Array.from({ length: 10 }, (_, index) => {
    const forecast = index >= 5;
    const base = 1000 + index * 40;
    return {
      period: `2026-${String(index + 1).padStart(2, "0")}-01`,
      kind: forecast ? "forecast" : "actual",
      actual: forecast ? null : base,
      forecast: forecast ? base : null,
      lower_bound: forecast ? base - 90 : null,
      upper_bound: forecast ? base + 90 : null,
      best_case: forecast ? base + 90 : null,
      base_case: forecast ? base : null,
      worst_case: forecast ? base - 90 : null,
    };
  }),
};

const SERIES = {
  run_id: RUN_ID,
  group_by: ["region"],
  sort: "value_at_risk",
  total: 0,
  limit: 50,
  offset: 0,
  currency: true,
  rows: [],
  has_more: false,
};

const HEALTH = {
  status: "ok",
  database: "ok",
  database_target: "local",
  database_host: "localhost",
  supabase_configured: false,
  storage_writable: true,
  forecast_workers: 1,
  max_upload_mb: 50,
  unavailable_models: [],
};

/**
 * A complete deployment. Prophet is available here so the picker under test
 * matches the shipped image; the unavailable path has its own coverage in the
 * backend suite, and greying a model out here would only make these specs
 * assert on a deployment nobody runs.
 */
const CAPABILITIES = {
  models: [
    { model: "naive", label: "Naive", available: true, reason: null },
    { model: "seasonal_naive", label: "Seasonal Naive", available: true, reason: null },
    { model: "holt_winters", label: "Holt-Winters", available: true, reason: null },
    { model: "ets", label: "Auto-ETS", available: true, reason: null },
    { model: "theta", label: "Theta", available: true, reason: null },
    { model: "croston", label: "Croston (Intermittent)", available: true, reason: null },
    { model: "sarimax", label: "SARIMAX", available: true, reason: null },
    { model: "prophet", label: "Prophet", available: true, reason: null },
    { model: "gradient_boosting", label: "Gradient Boosting", available: true, reason: null },
    { model: "ensemble", label: "Ensemble", available: true, reason: null },
  ],
  unavailable_models: [],
};

/** Route every API call to a fixture. Call it before the first navigation. */
export async function stubApi(page: Page): Promise<void> {
  await page.route("**/api/**", async (route) => {
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: CORS, body: "" });
      return;
    }

    const { pathname } = new URL(route.request().url());
    const json = (body: unknown) =>
      route.fulfill({
        status: 200,
        headers: CORS,
        contentType: "application/json",
        body: JSON.stringify(body),
      });

    if (pathname.endsWith("/api/health/capabilities")) return json(CAPABILITIES);
    if (pathname.endsWith("/api/health")) return json(HEALTH);
    if (pathname.endsWith("/api/dashboard/summary")) return json(SUMMARY);
    if (pathname.endsWith("/api/dashboard/breakdown")) return json(BREAKDOWN);
    if (pathname.endsWith("/api/dashboard/drivers")) return json(DRIVERS);
    if (pathname.endsWith("/api/insights")) return json(INSIGHTS);
    if (pathname.endsWith("/metrics")) return json(METRICS);
    if (pathname.endsWith("/points")) return json(POINTS);
    if (pathname.endsWith("/series")) return json(SERIES);
    // Both of these are bare arrays, not envelopes. Getting it wrong throws
    // inside a modal that is mounted on every page, which takes the whole
    // shell down with it.
    if (pathname.endsWith("/api/connectors/types")) return json([]);
    if (pathname.endsWith("/api/connectors")) return json([]);
    if (pathname.endsWith("/api/datasets")) {
      return json({
        total: 0,
        limit: 50,
        offset: 0,
        sort: "created_at",
        ready: 0,
        row_count: 0,
        file_size_bytes: 0,
        rows: [],
      });
    }

    // Anything a panel asks for that is not listed above still gets a
    // well-formed empty answer rather than a network error.
    return json({ run_id: RUN_ID, items: [], rows: [], points: [] });
  });
}

/** The dashboard, loaded and populated. */
export async function loadDashboard(page: Page): Promise<void> {
  await stubApi(page);
  await page.goto("/dashboard");
  await page.waitForSelector('[data-workspace="data"]', { timeout: 20_000 });
}
