import type { StoredModelConfig, ModelEndpoint, ModelTier } from "./types";

const STORAGE_KEY = "text-to-sql-model-config";
const CURRENT_VERSION = 1 as const;

function createDefaultEndpoint(): ModelEndpoint {
  return {
    enabled: false,
    base_url: "",
    api_key: "",
    model_name: "",
  };
}

export function getDefaultModelConfig(): StoredModelConfig {
  return {
    version: CURRENT_VERSION,
    models: {
      simple: createDefaultEndpoint(),
      standard: createDefaultEndpoint(),
      complex: createDefaultEndpoint(),
      fallback: createDefaultEndpoint(),
    },
    updatedAt: new Date().toISOString(),
  };
}

export function getModelConfig(): StoredModelConfig {
  if (typeof window === "undefined") {
    return getDefaultModelConfig();
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return getDefaultModelConfig();
    const parsed = JSON.parse(raw) as StoredModelConfig;
    if (!parsed || typeof parsed !== "object" || parsed.version !== CURRENT_VERSION) {
      return getDefaultModelConfig();
    }
    // Ensure all tiers exist
    const defaults = getDefaultModelConfig();
    return {
      version: CURRENT_VERSION,
      models: {
        simple: parsed.models?.simple ?? defaults.models.simple,
        standard: parsed.models?.standard ?? defaults.models.standard,
        complex: parsed.models?.complex ?? defaults.models.complex,
        fallback: parsed.models?.fallback ?? defaults.models.fallback,
      },
      updatedAt: parsed.updatedAt ?? new Date().toISOString(),
    };
  } catch {
    return getDefaultModelConfig();
  }
}

export function setModelConfig(config: StoredModelConfig): void {
  if (typeof window === "undefined") return;
  const toStore: StoredModelConfig = {
    ...config,
    version: CURRENT_VERSION,
    updatedAt: new Date().toISOString(),
  };
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(toStore));
}

export function clearModelConfig(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(STORAGE_KEY);
}

export function updateModelEndpoint(
  tier: ModelTier,
  endpoint: ModelEndpoint,
): StoredModelConfig {
  const current = getModelConfig();
  const updated: StoredModelConfig = {
    ...current,
    models: {
      ...current.models,
      [tier]: endpoint,
    },
  };
  setModelConfig(updated);
  return updated;
}

export function isModelConfigured(config: StoredModelConfig): boolean {
  return (Object.keys(config.models) as ModelTier[]).some(
    (tier) => config.models[tier].enabled,
  );
}
