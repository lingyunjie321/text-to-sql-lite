import { describe, expect, it } from "vitest";

import {
  buildWorkbenchQueryRequest,
  resolveWorkbenchProfileSelection,
} from "./Workbench";

describe("Workbench query request", () => {
  it("sends exactly the selected model and datasource Profile IDs", () => {
    const request = buildWorkbenchQueryRequest(
      "列出电影",
      "local-postgres",
      "local-model",
    );

    expect(request).toEqual({
      question: "列出电影",
      datasource_id: "local-postgres",
      model_profile_id: "local-model",
      debug: false,
    });
  });

  it("blocks querying when either current Profile is missing", async () => {
    await expect(
      resolveWorkbenchProfileSelection({
        getModelId: () => "local-model",
        getDatasourceId: () => null,
        listModelIds: async () => ["local-model"],
        listDatasourceIds: async () => ["local-postgres"],
        clearModelId: () => undefined,
        clearDatasourceId: () => undefined,
      }),
    ).resolves.toEqual({
      ok: false,
      message: "请先在设置页配置并选择当前模型和数据源。",
    });
  });

  it("clears deleted Profile selections and asks the user to select again", async () => {
    let modelCleared = false;
    let datasourceCleared = false;
    const result = await resolveWorkbenchProfileSelection({
      getModelId: () => "deleted-model",
      getDatasourceId: () => "deleted-datasource",
      listModelIds: async () => ["kept-model"],
      listDatasourceIds: async () => ["kept-datasource"],
      clearModelId: () => {
        modelCleared = true;
      },
      clearDatasourceId: () => {
        datasourceCleared = true;
      },
    });

    expect(result).toEqual({
      ok: false,
      message: "当前模型或数据源已不存在，请在设置页重新选择。",
    });
    expect(modelCleared).toBe(true);
    expect(datasourceCleared).toBe(true);
  });
});
