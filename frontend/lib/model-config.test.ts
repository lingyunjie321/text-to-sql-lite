import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearModelConfig,
  getDefaultModelConfig,
  getModelConfig,
  isModelConfigured,
  setModelConfig,
  updateModelEndpoint,
} from "./model-config";

const STORAGE_KEY = "text-to-sql-model-config";

function createLocalStorageMock() {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
}

const localStorageMock = createLocalStorageMock();

beforeEach(() => {
  localStorageMock.clear();
  vi.stubGlobal("window", { localStorage: localStorageMock });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getModelConfig", () => {
  it("returns defaults when window is undefined (SSR)", () => {
    vi.unstubAllGlobals();
    const config = getModelConfig();
    expect(config.version).toBe(1);
    expect(Object.keys(config.models)).toEqual([
      "simple",
      "standard",
      "complex",
      "fallback",
    ]);
  });

  it("returns defaults when storage is empty", () => {
    const config = getModelConfig();
    expect(config.version).toBe(1);
    for (const tier of ["simple", "standard", "complex", "fallback"] as const) {
      expect(config.models[tier]).toEqual({
        enabled: false,
        base_url: "",
        api_key: "",
        model_name: "",
      });
    }
  });

  it("returns defaults when stored JSON is corrupted", () => {
    localStorageMock.setItem(STORAGE_KEY, "{not valid json");
    expect(getModelConfig()).toEqual(getDefaultModelConfig());
  });

  it("returns defaults when stored version mismatches", () => {
    localStorageMock.setItem(
      STORAGE_KEY,
      JSON.stringify({ version: 999, models: {}, updatedAt: "x" }),
    );
    const config = getModelConfig();
    expect(config.models.simple.enabled).toBe(false);
  });

  it("fills missing tiers with defaults when stored config is partial", () => {
    localStorageMock.setItem(
      STORAGE_KEY,
      JSON.stringify({
        version: 1,
        models: {
          simple: { enabled: true, base_url: "https://x", api_key: "k", model_name: "m" },
        },
        updatedAt: "2025-01-01T00:00:00.000Z",
      }),
    );
    const config = getModelConfig();
    expect(config.models.simple.model_name).toBe("m");
    expect(config.models.fallback).toEqual({
      enabled: false,
      base_url: "",
      api_key: "",
      model_name: "",
    });
    expect(config.updatedAt).toBe("2025-01-01T00:00:00.000Z");
  });
});

describe("setModelConfig / clearModelConfig", () => {
  it("round-trips a config through localStorage", () => {
    const config = getDefaultModelConfig();
    config.models.standard = {
      enabled: true,
      base_url: "https://api.example.com",
      api_key: "sk-1",
      model_name: "gpt-4o",
    };
    setModelConfig(config);

    const raw = localStorageMock.getItem(STORAGE_KEY);
    expect(raw).not.toBeNull();
    const loaded = getModelConfig();
    expect(loaded.models.standard).toEqual(config.models.standard);
  });

  it("forces version and refreshes updatedAt on write", () => {
    const config = getDefaultModelConfig();
    config.updatedAt = "2000-01-01T00:00:00.000Z";
    setModelConfig(config);
    const stored = JSON.parse(localStorageMock.getItem(STORAGE_KEY)!);
    expect(stored.version).toBe(1);
    expect(stored.updatedAt).not.toBe("2000-01-01T00:00:00.000Z");
  });

  it("clearModelConfig removes the stored value", () => {
    setModelConfig(getDefaultModelConfig());
    clearModelConfig();
    expect(localStorageMock.getItem(STORAGE_KEY)).toBeNull();
    expect(getModelConfig()).toEqual(getDefaultModelConfig());
  });

  it("is a no-op when window is undefined", () => {
    vi.unstubAllGlobals();
    expect(() => setModelConfig(getDefaultModelConfig())).not.toThrow();
    expect(() => clearModelConfig()).not.toThrow();
  });
});

describe("updateModelEndpoint", () => {
  it("updates a single tier and persists it", () => {
    const updated = updateModelEndpoint("complex", {
      enabled: true,
      base_url: "https://big-model",
      api_key: "sk-c",
      model_name: "o1",
    });
    expect(updated.models.complex.model_name).toBe("o1");
    expect(updated.models.simple.enabled).toBe(false);
    expect(getModelConfig().models.complex.enabled).toBe(true);
  });
});

describe("isModelConfigured", () => {
  it("is false for the default config", () => {
    expect(isModelConfigured(getDefaultModelConfig())).toBe(false);
  });

  it("is true when any tier is enabled", () => {
    const config = getDefaultModelConfig();
    config.models.fallback.enabled = true;
    expect(isModelConfigured(config)).toBe(true);
  });
});
