/**
 * What each metric is, in the words a planner would use.
 *
 * The name alone is not a reading. "RMSSE 0.84" says nothing until you know it
 * is scaled against the series' own history and that under one beats the naive
 * forecast — so the label carries the sentence and the panel carries the name.
 */
export type MetricLabel = {
  short: string;
  meaning: string;
  /** How to render it: a percentage, a ratio around 1, or the data's own units. */
  unit: "percent" | "ratio" | "value";
  /** True where a bigger number is the better one. */
  higherIsBetter?: boolean;
};

export const METRIC_LABELS: Record<string, MetricLabel> = {
  wmape: {
    short: "wMAPE",
    meaning: "Error as a share of the volume it was measured on.",
    unit: "percent",
  },
  mae: { short: "MAE", meaning: "The average miss, in the data's own units.", unit: "value" },
  medae: {
    short: "Median error",
    meaning: "The typical miss. Far below MAE means the error sits in a few periods.",
    unit: "value",
  },
  rmse: {
    short: "RMSE",
    meaning: "The average miss, with the big ones counting for more.",
    unit: "value",
  },
  bias: {
    short: "Bias",
    meaning: "Which way it leans. Positive means the forecast ran high.",
    unit: "value",
  },
  relative_bias: {
    short: "Lean",
    meaning: "The same lean as a share of volume, so it reads beside wMAPE.",
    unit: "percent",
  },
  mase: {
    short: "MASE",
    meaning: "Scaled against this series' own history. Under 1 beats the naive forecast.",
    unit: "ratio",
  },
  rmsse: {
    short: "RMSSE",
    meaning: "MASE with the big misses weighted. Under 1 beats the naive forecast.",
    unit: "ratio",
  },
  theil_u2: {
    short: "Skill vs naive",
    meaning: "Under 1 means the model earned its place; over 1 means it did not.",
    unit: "ratio",
  },
  mape: { short: "MAPE", meaning: "Error as a percentage of each actual.", unit: "percent" },
  smape: { short: "sMAPE", meaning: "Symmetric percentage error.", unit: "percent" },
  rmsle: {
    short: "Log error",
    meaning: "Proportional error, for series that move across orders of magnitude.",
    unit: "ratio",
  },
  r_squared: {
    short: "R²",
    meaning: "Share of the movement the forecast accounts for. Can go below zero.",
    unit: "ratio",
    higherIsBetter: true,
  },
  residual_acf1: {
    short: "Leftover signal",
    meaning: "Near zero is healthy. Away from it means something predictable was missed.",
    unit: "ratio",
  },
};

export function metricLabel(name: string): MetricLabel {
  return METRIC_LABELS[name] ?? { short: name, meaning: "", unit: "value" };
}
