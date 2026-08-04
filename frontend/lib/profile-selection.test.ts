import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  LEGACY_DATASOURCE_CONFIG_KEY,
  LEGACY_MODEL_CONFIG_KEY,
  SELECTED_DATASOURCE_PROFILE_KEY,
  SELECTED_MODEL_PROFILE_KEY,
  getSelectedDatasourceProfileId,
  reconcileSelectedDatasourceProfileId,
  reconcileSelectedModelProfileId,
  removeLegacyDatasourceConfig,
  setSelectedDatasourceProfileId,
  removeLegacyModelConfig,
  setSelectedModelProfileId,
} from "./profile-selection";

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

describe("model profile selection", () => {
  it("stores only a valid profile id", () => {
    setSelectedModelProfileId("local-model");

    expect(localStorageMock.getItem(SELECTED_MODEL_PROFILE_KEY)).toBe("local-model");
    expect(() => setSelectedModelProfileId("../secret")).toThrow();
  });

  it("is a no-op for an invalid id during SSR", () => {
    vi.unstubAllGlobals();

    expect(() => setSelectedModelProfileId("../secret")).not.toThrow();
  });

  it("clears a selection missing from the server list", () => {
    localStorageMock.setItem(SELECTED_MODEL_PROFILE_KEY, "gone");

    expect(reconcileSelectedModelProfileId(["kept"])).toBeNull();
    expect(localStorageMock.getItem(SELECTED_MODEL_PROFILE_KEY)).toBeNull();
  });

  it("deletes legacy model secrets without reading them", () => {
    localStorageMock.setItem(LEGACY_MODEL_CONFIG_KEY, "sentinel-secret-not-json");
    const getItem = vi.spyOn(localStorageMock, "getItem");

    removeLegacyModelConfig();

    expect(getItem).not.toHaveBeenCalled();
    expect(localStorageMock.getItem(LEGACY_MODEL_CONFIG_KEY)).toBeNull();
  });
});

describe("datasource profile selection", () => {
  it("stores only the non-sensitive current datasource id", () => {
    setSelectedDatasourceProfileId("local-postgres");

    expect(localStorageMock.getItem(SELECTED_DATASOURCE_PROFILE_KEY)).toBe(
      "local-postgres",
    );
    expect(getSelectedDatasourceProfileId()).toBe("local-postgres");
    expect(JSON.stringify(localStorageMock)).not.toContain("password");
    expect(JSON.stringify(localStorageMock)).not.toContain("postgresql://");
  });

  it("clears a datasource selection missing from the server list", () => {
    localStorageMock.setItem(SELECTED_DATASOURCE_PROFILE_KEY, "gone");

    expect(reconcileSelectedDatasourceProfileId(["kept"])).toBeNull();
    expect(localStorageMock.getItem(SELECTED_DATASOURCE_PROFILE_KEY)).toBeNull();
  });

  it("deletes the legacy database value without reading or migrating it", () => {
    localStorageMock.setItem(
      LEGACY_DATASOURCE_CONFIG_KEY,
      "postgresql://user:sentinel-secret@localhost/db",
    );
    const getItem = vi.spyOn(localStorageMock, "getItem");
    getItem.mockClear();

    removeLegacyDatasourceConfig();

    expect(getItem).not.toHaveBeenCalled();
    expect(localStorageMock.getItem(LEGACY_DATASOURCE_CONFIG_KEY)).toBeNull();
  });
});
