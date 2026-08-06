import type { LlmRunFields } from "@/types/api";

export interface LlmConfig {
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
  inputCostPerMillion: number | null;
  outputCostPerMillion: number | null;
}

export const PROVIDERS: { value: string; label: string; hint: string }[] = [
  { value: "openai", label: "OpenAI", hint: "GPT models, from platform.openai.com" },
  { value: "anthropic", label: "Anthropic", hint: "Claude models, from console.anthropic.com" },
  { value: "gemini", label: "Google Gemini", hint: "Gemini models, from Google AI Studio" },
  { value: "xai", label: "xAI", hint: "Grok models, from console.x.ai" },
  { value: "groq", label: "Groq", hint: "Open models, served fast" },
  { value: "openrouter", label: "OpenRouter", hint: "One key for many providers" },
  { value: "custom", label: "Ollama or self-hosted", hint: "Anything with an OpenAI-shaped API" },
];

export const PROVIDER_MODELS: Record<string, string[]> = {
  openai: ["gpt-4o-mini", "gpt-4o"],
  anthropic: ["claude-haiku-4-5-20251001", "claude-sonnet-5", "claude-opus-5"],
  groq: ["llama-3.3-70b-versatile", "deepseek-r1-distill-llama-70b"],
  xai: ["grok-2-latest", "grok-beta"],
  gemini: ["gemini-2.5-flash", "gemini-2.5-pro"],
  openrouter: ["anthropic/claude-haiku-4.5", "openai/gpt-4o-mini", "google/gemini-2.5-flash"],
  custom: [],
};

export const PROVIDERS_NEEDING_BASE_URL = new Set(["custom", "openrouter"]);

const STORAGE_KEY = "forecast_hub_llm_config";

export const EMPTY_LLM_CONFIG: LlmConfig = {
  provider: "openai",
  apiKey: "",
  model: "gpt-4o-mini",
  baseUrl: "",
  inputCostPerMillion: null,
  outputCostPerMillion: null,
};

export function defaultModelFor(provider: string): string {
  return PROVIDER_MODELS[provider]?.[0] ?? "";
}

export function loadLlmConfig(): LlmConfig {
  if (typeof window === "undefined") return EMPTY_LLM_CONFIG;

  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (!saved) return EMPTY_LLM_CONFIG;

    const parsed = JSON.parse(saved) as Partial<LlmConfig>;
    return {
      provider: parsed.provider ?? EMPTY_LLM_CONFIG.provider,
      apiKey: parsed.apiKey ?? "",
      model: parsed.model ?? EMPTY_LLM_CONFIG.model,
      baseUrl: parsed.baseUrl ?? "",
      inputCostPerMillion:
        typeof parsed.inputCostPerMillion === "number" ? parsed.inputCostPerMillion : null,
      outputCostPerMillion:
        typeof parsed.outputCostPerMillion === "number" ? parsed.outputCostPerMillion : null,
    };
  } catch {
    return EMPTY_LLM_CONFIG;
  }
}

export function saveLlmConfig(config: LlmConfig): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  } catch {
  }
}

export function clearLlmConfig(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
  }
}

export function llmRunFields(config: LlmConfig): LlmRunFields {
  const apiKey = config.apiKey.trim();
  if (!apiKey) {
    return {
      llm_provider: null,
      llm_api_key: null,
      llm_model: null,
      llm_base_url: null,
      llm_input_cost_per_million: config.inputCostPerMillion,
      llm_output_cost_per_million: config.outputCostPerMillion,
    };
  }

  return {
    llm_provider: config.provider || null,
    llm_api_key: apiKey,
    llm_model: config.model.trim() || null,
    llm_base_url: config.baseUrl.trim() || null,
    llm_input_cost_per_million: config.inputCostPerMillion,
    llm_output_cost_per_million: config.outputCostPerMillion,
  };
}
