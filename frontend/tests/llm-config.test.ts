import { beforeEach, describe, expect, it } from "vitest";

import {
  EMPTY_LLM_CONFIG,
  PROVIDERS,
  PROVIDERS_NEEDING_BASE_URL,
  PROVIDER_MODELS,
  clearLlmConfig,
  defaultModelFor,
  llmRunFields,
  loadLlmConfig,
  saveLlmConfig,
} from "@/lib/llm-config";

beforeEach(() => {
  window.localStorage.clear();
});

describe("storage", () => {
  it("round-trips a saved config", () => {
    saveLlmConfig({
      provider: "groq",
      apiKey: "key",
      model: "llama",
      baseUrl: "",
      inputCostPerMillion: 0.59,
      outputCostPerMillion: 0.79,
    });
    expect(loadLlmConfig()).toEqual({
      provider: "groq",
      apiKey: "key",
      model: "llama",
      baseUrl: "",
      inputCostPerMillion: 0.59,
      outputCostPerMillion: 0.79,
    });
  });

  it("falls back to defaults when nothing is stored", () => {
    expect(loadLlmConfig()).toEqual(EMPTY_LLM_CONFIG);
  });

  it("survives a corrupted entry rather than throwing", () => {
    window.localStorage.setItem("forecast_hub_llm_config", "{not json");
    expect(loadLlmConfig()).toEqual(EMPTY_LLM_CONFIG);
  });

  it("fills in fields a partial entry is missing", () => {
    window.localStorage.setItem("forecast_hub_llm_config", JSON.stringify({ provider: "xai" }));
    expect(loadLlmConfig()).toEqual({ ...EMPTY_LLM_CONFIG, provider: "xai" });
  });

  it("clears", () => {
    saveLlmConfig({ ...EMPTY_LLM_CONFIG, provider: "groq", apiKey: "key", model: "llama" });
    clearLlmConfig();
    expect(loadLlmConfig()).toEqual(EMPTY_LLM_CONFIG);
  });
});

describe("llmRunFields", () => {
  it("sends nothing without a key, so the server's own config wins", () => {
    expect(
      llmRunFields({ ...EMPTY_LLM_CONFIG, apiKey: "   ", model: "gpt-4o" }),
    ).toEqual({
      llm_provider: null,
      llm_api_key: null,
      llm_model: null,
      llm_base_url: null,
      llm_input_cost_per_million: null,
      llm_output_cost_per_million: null,
    });
  });

  it("trims what it sends and nulls the blanks", () => {
    expect(
      llmRunFields({
        ...EMPTY_LLM_CONFIG,
        apiKey: " sk-1 ",
        model: " gpt-4o ",
        inputCostPerMillion: 2.5,
        outputCostPerMillion: 10,
      }),
    ).toEqual({
      llm_provider: "openai",
      llm_api_key: "sk-1",
      llm_model: "gpt-4o",
      llm_base_url: null,
      llm_input_cost_per_million: 2.5,
      llm_output_cost_per_million: 10,
    });
  });
});

describe("defaultModelFor", () => {
  // Named model ids move as providers ship new ones, so this pins the rule —
  // the first of the provider's list — rather than today's answer to it.
  it("picks the first model of a known provider and empties an unknown one", () => {
    for (const [provider, models] of Object.entries(PROVIDER_MODELS)) {
      expect(defaultModelFor(provider)).toBe(models[0] ?? "");
    }
    expect(defaultModelFor("custom")).toBe("");
    expect(defaultModelFor("nope")).toBe("");
  });

  it("offers a model for every provider that is not self-hosted", () => {
    for (const provider of PROVIDERS) {
      if (PROVIDERS_NEEDING_BASE_URL.has(provider.value)) continue;
      expect(defaultModelFor(provider.value), provider.value).not.toBe("");
    }
  });
});
