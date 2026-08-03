import { describe, expect, it, vi } from "vitest";

import {
  deleteModelProfileFromState,
  loadModelProfileState,
  modelProfileCountStatus,
} from "./model-profile-coordinator";
import type { ModelProfileResponse } from "../../lib/model-profiles";

const profileA: ModelProfileResponse = {
  id: "model-a",
  name: "Model A",
  provider_type: "openai_compatible",
  base_url: "http://localhost:11434/v1",
  model_name: "model-a",
  embedding_base_url: null,
  embedding_model: null,
  embedding_dimension: null,
  generation_credential_status: "configured",
  embedding_credential_status: "not_applicable",
};

const profileB: ModelProfileResponse = {
  ...profileA,
  id: "model-b",
  name: "Model B",
  model_name: "model-b",
};

describe("model Profile coordinator", () => {
  it("removes the legacy config before listing and reconciles only after the list arrives", async () => {
    const events: string[] = [];

    const result = await loadModelProfileState({
      removeLegacyConfig: () => events.push("remove-legacy"),
      listProfiles: async () => {
        events.push("list");
        return [profileA];
      },
      reconcileSelectedId: (ids) => {
        events.push(`reconcile:${ids.join(",")}`);
        return "model-a";
      },
    });

    expect(events).toEqual([
      "remove-legacy",
      "list",
      "reconcile:model-a",
    ]);
    expect(result).toEqual({
      profiles: [profileA],
      selectedId: "model-a",
      profileCount: 1,
    });
  });

  it("settles a successful delete locally, clears the current selection, and does not issue a list request", async () => {
    const listProfiles = vi.fn<() => Promise<ModelProfileResponse[]>>();
    const clearSelectedId = vi.fn();

    const result = await deleteModelProfileFromState(
      [profileA, profileB],
      "model-a",
      {
        deleteProfile: async () => undefined,
        listProfiles,
        getSelectedId: () => "model-a",
        clearSelectedId,
        reconcileSelectedId: () => null,
        isMissingError: () => false,
      },
    );

    expect(result).toEqual({
      profiles: [profileB],
      selectedId: null,
      profileCount: 1,
      refreshed: false,
    });
    expect(clearSelectedId).toHaveBeenCalledOnce();
    expect(listProfiles).not.toHaveBeenCalled();
  });

  it("preserves a newer selection when an older profile deletion settles", async () => {
    const clearSelectedId = vi.fn();

    const result = await deleteModelProfileFromState(
      [profileA, profileB],
      "model-a",
      {
        deleteProfile: async () => undefined,
        listProfiles: async () => {
          throw new Error("a 204 delete must not refresh");
        },
        getSelectedId: () => "model-b",
        clearSelectedId,
        reconcileSelectedId: () => null,
        isMissingError: () => false,
      },
    );

    expect(result.selectedId).toBe("model-b");
    expect(clearSelectedId).not.toHaveBeenCalled();
  });

  it("refreshes and reconciles after a missing-profile delete conflict", async () => {
    const conflict = new Error("missing");
    const events: string[] = [];

    const result = await deleteModelProfileFromState(
      [profileA, profileB],
      "model-a",
      {
        deleteProfile: async () => {
          events.push("delete");
          throw conflict;
        },
        listProfiles: async () => {
          events.push("list");
          return [profileB];
        },
        getSelectedId: () => "model-a",
        clearSelectedId: () => events.push("clear"),
        reconcileSelectedId: (ids) => {
          events.push(`reconcile:${ids.join(",")}`);
          return null;
        },
        isMissingError: (error) => error === conflict,
      },
    );

    expect(events).toEqual(["delete", "list", "reconcile:model-b"]);
    expect(result).toEqual({
      profiles: [profileB],
      selectedId: null,
      profileCount: 1,
      refreshed: true,
    });
  });
});

describe("settings state helpers", () => {
  it("distinguishes loading, unavailable, empty, and configured model counts", () => {
    expect(modelProfileCountStatus(undefined)).toBe("加载中");
    expect(modelProfileCountStatus(null)).toBe("不可用");
    expect(modelProfileCountStatus(0)).toBe("未配置");
    expect(modelProfileCountStatus(2)).toBe("已配置");
  });
});
