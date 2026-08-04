/**
 * Optional per-browser LLM credentials for the insight rewriter. The backend
 * has its own server-side configuration; anything set here is sent with a run
 * request and overrides it for that run only.
 */

export interface LlmConfig {
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

export const PROVIDERS: { value: string; label: string }[] = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic (Claude)" },
  { value: "groq", label: "Groq" },
  { value: "xai", label: "xAI (Grok)" },
  { value: "gemini", label: "Google Gemini" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "custom", label: "Custom / Ollama" },
];

export const PROVIDER_MODELS: Record<string, string[]> = {
  openai: ["gpt-4o-mini", "gpt-4o", "o3-mini"],
  anthropic: ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"],
  groq: ["llama-3.3-70b-versatile", "deepseek-r1-distill-llama-70b"],
  xai: ["grok-2-latest", "grok-beta"],
  gemini: ["gemini-2.5-flash", "gemini-2.5-pro"],
  openrouter: ["anthropic/claude-3.5-sonnet", "openai/gpt-4o-mini", "google/gemini-2.5-flash"],
  custom: [],
};

/** Providers that talk to an endpoint the user has to name themselves. */
export const PROVIDERS_NEEDING_BASE_URL = new Set(["custom", "openrouter"]);

const STORAGE_KEY = "forecast_hub_llm_config";

export const EMPTY_LLM_CONFIG: LlmConfig = {
  provider: "openai",
  apiKey: "",
  model: "gpt-4o-mini",
  baseUrl: "",
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
    // A browser with storage disabled still gets a working dashboard; the
    // config just does not survive the reload.
  }
}

export function clearLlmConfig(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* see saveLlmConfig */
  }
}

/** Shapes the stored config into the fields a run request expects. */
export function llmRunFields(config: LlmConfig) {
  const apiKey = config.apiKey.trim();
  if (!apiKey) {
    return {
      llm_provider: null,
      llm_api_key: null,
      llm_model: null,
      llm_base_url: null,
    };
  }

  return {
    llm_provider: config.provider || null,
    llm_api_key: apiKey,
    llm_model: config.model.trim() || null,
    llm_base_url: config.baseUrl.trim() || null,
  };
}
