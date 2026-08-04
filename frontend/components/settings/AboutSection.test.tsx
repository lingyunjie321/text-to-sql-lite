import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AboutSection, clearBrowserPreferences } from "./AboutSection";
import {
  LEGACY_MODEL_CONFIG_KEY,
  SELECTED_MODEL_PROFILE_KEY,
} from "@/lib/profile-selection";

const LEGACY_DATASOURCE_CONFIG_KEY = "text-to-sql-db-config";

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

describe("AboutSection browser storage boundary", () => {
  it("describes backend model storage and browser-only preferences", () => {
    const markup = renderToStaticMarkup(
      <AboutSection onToast={() => undefined} onConfigCleared={() => undefined} />,
    );

    expect(markup).toContain("模型 Profile 保存在本地后端");
    expect(markup).toContain("API Key 仅保存在当前后端进程内存");
    expect(markup).toContain("浏览器仅保存当前模型 Profile ID");
    expect(markup).toContain("清除浏览器偏好");
    expect(markup).not.toContain("API Key 和数据库密码存储在 localStorage 中");
    expect(markup).not.toContain("清除所有配置");
  });

  it("clears only the known browser preference keys", () => {
    localStorageMock.setItem(SELECTED_MODEL_PROFILE_KEY, "local-model");
    localStorageMock.setItem(LEGACY_MODEL_CONFIG_KEY, "legacy-model-secret");
    localStorageMock.setItem(LEGACY_DATASOURCE_CONFIG_KEY, "legacy-db-secret");
    localStorageMock.setItem("unrelated-browser-entry", "must-stay");

    clearBrowserPreferences();

    expect(localStorageMock.getItem(SELECTED_MODEL_PROFILE_KEY)).toBeNull();
    expect(localStorageMock.getItem(LEGACY_MODEL_CONFIG_KEY)).toBeNull();
    expect(localStorageMock.getItem(LEGACY_DATASOURCE_CONFIG_KEY)).toBeNull();
    expect(localStorageMock.getItem("unrelated-browser-entry")).toBe("must-stay");
  });
});
