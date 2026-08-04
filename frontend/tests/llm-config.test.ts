import { beforeEach, describe, expect, it } from "vitest";

import {
  EMPTY_LLM_CONFIG,
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
    saveLlmConfig({ provider: "groq", apiKey: "key", model: "llama", baseUrl: "" });
    expect(loadLlmConfig()).toEqual({
      provider: "groq",
      apiKey: "key",
      model: "llama",
      baseUrl: "",
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
    saveLlmConfig({ provider: "groq", apiKey: "key", model: "llama", baseUrl: "" });
    clearLlmConfig();
    expect(loadLlmConfig()).toEqual(EMPTY_LLM_CONFIG);
  });
});

describe("llmRunFields", () => {
  it("sends nothing without a key, so the server's own config wins", () => {
    expect(llmRunFields({ provider: "openai", apiKey: "   ", model: "gpt-4o", baseUrl: "" })).toEqual(
      { llm_provider: null, llm_api_key: null, llm_model: null, llm_base_url: null },
    );
  });

  it("trims what it sends and nulls the blanks", () => {
    expect(
      llmRunFields({ provider: "openai", apiKey: " sk-1 ", model: " gpt-4o ", baseUrl: "" }),
    ).toEqual({
      llm_provider: "openai",
      llm_api_key: "sk-1",
      llm_model: "gpt-4o",
      llm_base_url: null,
    });
  });
});

describe("defaultModelFor", () => {
  it("picks the first model of a known provider and empties an unknown one", () => {
    expect(defaultModelFor("anthropic")).toBe("claude-3-5-sonnet-20241022");
    expect(defaultModelFor("custom")).toBe("");
    expect(defaultModelFor("nope")).toBe("");
  });
});
