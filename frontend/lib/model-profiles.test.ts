import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PasswordInput } from "../components/settings/PasswordInput";
import {
  ProfileApiError,
  buildModelTestRequest,
  buildModelWriteRequest,
  createModelProfile,
  listModelProfiles,
  parseModelProfileResponse,
  replaceModelProfile,
  testModelConnection,
  type ModelProfileFormValue,
  type ModelProfileResponse,
} from "./model-profiles";

const validResponse = {
  id: "local-model",
  name: "Local model",
  provider_type: "openai_compatible" as const,
  base_url: "http://localhost:11434/v1",
  model_name: "qwen2.5-coder",
  embedding_base_url: null,
  embedding_model: null,
  embedding_dimension: null,
  generation_credential_status: "configured" as const,
  embedding_credential_status: "not_applicable" as const,
};

const editValue = {
  id: "local-model",
  name: "Local model",
  baseUrl: "http://localhost:11434/v1",
  modelName: "qwen2.5-coder",
  apiKey: "",
  clearApiKey: false,
  embeddingEnabled: false,
  embeddingBaseUrl: "",
  embeddingModel: "",
  embeddingDimension: "",
  embeddingApiKey: "",
  clearEmbeddingApiKey: false,
};

const embeddingResponse = {
  ...validResponse,
  base_url: "https://models.example.test/v1",
  embedding_base_url: "https://embedding.example.test/v1",
  embedding_model: "text-embedding-3-small",
  embedding_dimension: 1536,
  embedding_credential_status: "configured" as const,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PasswordInput", () => {
  it("lets model credential fields request new-password autocomplete without labeling the secret", () => {
    const markup = renderToStaticMarkup(
      React.createElement(PasswordInput, {
        value: "sentinel-secret",
        onChange: () => undefined,
        autoComplete: "new-password",
      }),
    );

    expect(markup).toContain('autoComplete="new-password"');
    expect(markup).not.toContain('aria-label="sentinel-secret"');
  });
});

describe("ModelProfileForm", () => {
  it("renders a create form with a fixed provider and collapsed optional embedding", async () => {
    const formModule = await import(
      "../components/settings/ModelProfileForm"
    ).catch(() => null);

    expect(formModule).not.toBeNull();
    if (formModule === null) return;

    const markup = renderToStaticMarkup(
      React.createElement(formModule.ModelProfileForm, {
        mode: "create",
        onCancel: () => undefined,
        onSaved: () => undefined,
      }),
    );

    expect(markup).toContain("添加模型 Profile");
    expect(markup).toContain("openai_compatible");
    expect(markup).toContain('name="id"');
    expect(markup).not.toMatch(/<input[^>]*readOnly=""[^>]*name="id"/);
    expect(markup.match(/autoComplete="new-password"/g)).toHaveLength(1);
    expect(markup).not.toContain('placeholder="••••••••"');
    expect(markup).toContain("可选：无鉴权本地服务可留空");
    expect(markup).toContain("Embedding（可选增强）");
    expect(markup).toContain(
      'role="switch" aria-checked="false" aria-label="启用 Embedding"',
    );
    expect(markup).not.toContain('name="embeddingBaseUrl"');
    expect(markup).not.toContain("保存后会清除 Embedding 配置和凭据");
    expect(markup).toContain("连接状态：未测试");
    expect(markup).toMatch(/<button[^>]*type="submit"[^>]*>保存 Profile<\/button>/);
    expect(markup).not.toContain("fallback");
  });

  it("keeps edit credentials blank and makes the immutable id read only", async () => {
    const { ModelProfileForm } = await import(
      "../components/settings/ModelProfileForm"
    );

    const markup = renderToStaticMarkup(
      React.createElement(ModelProfileForm, {
        mode: "edit",
        profile: embeddingResponse,
        onCancel: () => undefined,
        onSaved: () => undefined,
      }),
    );

    expect(markup).toMatch(/<input[^>]*readOnly=""[^>]*name="id"/);
    expect(markup).toContain("留空则保留当前凭据");
    expect(markup).toContain("清除已保存凭据");
    expect(markup.match(/autoComplete="new-password"/g)).toHaveLength(2);
    expect(markup).not.toContain('placeholder="••••••••"');
    expect(markup.match(/留空则保留；测试时可能需重新输入/g)).toHaveLength(2);
    expect(markup).not.toContain("sentinel-secret");
  });

  it("resets a successful test and cancels credential clearing when a new key is entered", async () => {
    const {
      createModelFormState,
      settleModelTestState,
      updateModelFormState,
      willClearEmbedding,
    } = await import(
      "../components/settings/ModelProfileForm"
    );
    const testedState = {
      ...createModelFormState(embeddingResponse),
      value: {
        ...createModelFormState(embeddingResponse).value,
        clearApiKey: true,
      },
      testState: {
        status: "success" as const,
        message: "生成模型与 Embedding 均可用",
      },
    };

    const changed = updateModelFormState(testedState, {
      apiKey: "replacement-key",
    });

    expect(changed.value.apiKey).toBe("replacement-key");
    expect(changed.value.clearApiKey).toBe(false);
    expect(changed.testState).toEqual({ status: "untested" });
    expect(
      settleModelTestState(changed, testedState.revision, {
        status: "success",
        message: "stale success",
      }).testState,
    ).toEqual({ status: "untested" });

    const embeddingDisabled = updateModelFormState(testedState, {
      embeddingEnabled: false,
    });
    expect(willClearEmbedding(embeddingResponse, embeddingDisabled.value)).toBe(
      true,
    );
  });

  it("validates the exact profile id, URLs, and enabled embedding dimension", async () => {
    const { validateModelFormValue } = await import(
      "../components/settings/ModelProfileForm"
    );

    expect(
      validateModelFormValue({
        ...editValue,
        id: "BAD ID",
        name: " ",
        baseUrl: "not a url",
        modelName: "",
        embeddingEnabled: true,
        embeddingBaseUrl: "invalid",
        embeddingModel: " ",
        embeddingDimension: "0",
      }),
    ).toEqual({
      id: "Profile ID 只能包含小写字母、数字、下划线和连字符，长度不超过 64 位",
      name: "请输入 Profile 名称",
      baseUrl: "请输入有效的 HTTP 或 HTTPS 地址",
      modelName: "请输入生成模型名称",
      embeddingBaseUrl: "请输入有效的 HTTP 或 HTTPS 地址",
      embeddingModel: "请输入 Embedding 模型名称",
      embeddingDimension: "请输入 1 到 1000000 之间的整数",
    });
  });

  it("requires credential re-entry only for configured authenticated edit endpoints", async () => {
    const { credentialReentryMessage, createModelFormState } = await import(
      "../components/settings/ModelProfileForm"
    );

    expect(
      credentialReentryMessage(
        embeddingResponse,
        createModelFormState(embeddingResponse).value,
      ),
    ).toBe("测试不会复用已保存凭据，请重新输入生成模型 API Key");
    expect(
      credentialReentryMessage(
        validResponse,
        createModelFormState(validResponse).value,
      ),
    ).toBeNull();
    expect(
      credentialReentryMessage(
        { ...validResponse, generation_credential_status: "missing" },
        createModelFormState({
          ...validResponse,
          generation_credential_status: "missing",
        }).value,
      ),
    ).toBeNull();
    expect(
      credentialReentryMessage(embeddingResponse, {
        ...createModelFormState(embeddingResponse).value,
        baseUrl: "https://alternate.example.test/v1",
      }),
    ).toBe("测试不会复用已保存凭据，请重新输入生成模型 API Key");
    expect(
      credentialReentryMessage(embeddingResponse, {
        ...createModelFormState(embeddingResponse).value,
        baseUrl: "https://127.attacker.test/v1",
      }),
    ).toBe("测试不会复用已保存凭据，请重新输入生成模型 API Key");
    expect(
      credentialReentryMessage(embeddingResponse, {
        ...createModelFormState(embeddingResponse).value,
        baseUrl: "http://127.0.0.1:1234/v1",
        apiKey: "",
        embeddingEnabled: false,
      }),
    ).toBeNull();
    expect(
      credentialReentryMessage(embeddingResponse, {
        ...createModelFormState(embeddingResponse).value,
        baseUrl: "https://models.example.test/v1/",
        clearApiKey: true,
      }),
    ).toBe("测试不会复用已保存凭据，请重新输入生成模型 API Key");
    expect(
      credentialReentryMessage(embeddingResponse, {
        ...createModelFormState(embeddingResponse).value,
        apiKey: "current-test-key",
        embeddingBaseUrl: "https://alternate-embedding.example.test/v1",
      }),
    ).toBe("测试不会复用已保存凭据，请重新输入 Embedding API Key");
    expect(
      credentialReentryMessage(embeddingResponse, {
        ...createModelFormState(embeddingResponse).value,
        apiKey: "current-test-key",
        embeddingBaseUrl: "https://127.attacker.test/v1",
      }),
    ).toBe("测试不会复用已保存凭据，请重新输入 Embedding API Key");
    expect(
      credentialReentryMessage(embeddingResponse, {
        ...createModelFormState(embeddingResponse).value,
        apiKey: "current-test-key",
        embeddingBaseUrl: "https://embedding.example.test/v1/",
      }),
    ).toBe("测试不会复用已保存凭据，请重新输入 Embedding API Key");
    expect(
      credentialReentryMessage(embeddingResponse, {
        ...createModelFormState(embeddingResponse).value,
        apiKey: "current-test-key",
        embeddingBaseUrl: "http://127.0.0.1:1234/v1",
      }),
    ).toBeNull();
  });

  it("warns that a configured generation credential will be cleared only for a changed normalized endpoint without a replacement", async () => {
    const { generationCredentialSaveWarning } = await import(
      "../components/settings/ModelProfileForm"
    );
    const original = createModelValue(embeddingResponse);

    expect(
      generationCredentialSaveWarning(embeddingResponse, {
        ...original,
        baseUrl: "https://alternate.example.test/v1",
      }),
    ).toBe(
      "生成模型 Base URL 已变更；未输入新 API Key 时，保存会清除当前凭据。",
    );
    expect(
      generationCredentialSaveWarning(embeddingResponse, {
        ...original,
        baseUrl: "https://MODELS.EXAMPLE.TEST:443/v1",
      }),
    ).toBeNull();
    expect(
      generationCredentialSaveWarning(embeddingResponse, {
        ...original,
        baseUrl: "https://alternate.example.test/v1",
        apiKey: "replacement-key",
      }),
    ).toBeNull();
  });

  it("warns that a configured embedding credential will be cleared for endpoint or model identity changes", async () => {
    const { embeddingCredentialSaveWarning } = await import(
      "../components/settings/ModelProfileForm"
    );
    const original = createModelValue(embeddingResponse);
    const expected =
      "Embedding 地址或模型已变更；未输入新 API Key 时，保存会清除当前凭据。";

    expect(
      embeddingCredentialSaveWarning(embeddingResponse, {
        ...original,
        embeddingBaseUrl: "https://alternate-embedding.example.test/v1",
      }),
    ).toBe(expected);
    expect(
      embeddingCredentialSaveWarning(embeddingResponse, {
        ...original,
        embeddingModel: "text-embedding-3-large",
      }),
    ).toBe(expected);
    expect(
      embeddingCredentialSaveWarning(embeddingResponse, {
        ...original,
        embeddingBaseUrl: "https://EMBEDDING.EXAMPLE.TEST:443/v1",
      }),
    ).toBeNull();
    expect(
      embeddingCredentialSaveWarning(embeddingResponse, {
        ...original,
        embeddingModel: "text-embedding-3-large",
        embeddingApiKey: "replacement-key",
      }),
    ).toBeNull();
  });

  it("maps test responses to useful generation and embedding outcomes", async () => {
    const { connectionTestState } = await import(
      "../components/settings/ModelProfileForm"
    );

    expect(
      connectionTestState({
        generation: "connected",
        embedding: "not_configured",
        embedding_error: null,
      }),
    ).toEqual({
      status: "success",
      message: "生成模型可用，BM25-only 可用",
    });
    expect(
      connectionTestState({
        generation: "connected",
        embedding: "connected",
        embedding_error: null,
      }),
    ).toEqual({
      status: "success",
      message: "生成模型与 Embedding 均可用",
    });
    expect(
      connectionTestState({
        generation: "connected",
        embedding: "unavailable",
        embedding_error: {
          code: "EMBEDDING_UNAVAILABLE",
          message: "sentinel upstream detail",
        },
      }),
    ).toEqual({
      status: "warning",
      message: "生成模型可用，Embedding 当前不可用；可继续使用 BM25-only",
    });
  });
});

describe("ModelProfileSection save settlement", () => {
  it("appends creates and replaces edits using the sanitized response", async () => {
    const sectionModule = await import(
      "../components/settings/ModelProfileSection"
    );
    const replacement = { ...validResponse, name: "Renamed model" };
    const created = {
      ...validResponse,
      id: "second-model",
      name: "Second model",
    };

    expect(sectionModule.settleSavedProfile([validResponse], replacement)).toEqual([
      replacement,
    ]);
    expect(sectionModule.settleSavedProfile([validResponse], created)).toEqual([
      validResponse,
      created,
    ]);
  });

  it("locks form entry while list state or another mutation is unsettled", async () => {
    const { modelProfileActionsLocked, modelProfileListHidden } = await import(
      "../components/settings/ModelProfileSection"
    );

    expect(
      modelProfileActionsLocked({
        loading: true,
        loadFailed: false,
        formOpen: false,
        deletePending: false,
      }),
    ).toBe(true);
    expect(
      modelProfileActionsLocked({
        loading: false,
        loadFailed: false,
        formOpen: false,
        deletePending: false,
      }),
    ).toBe(false);
    expect(
      modelProfileActionsLocked({
        loading: false,
        loadFailed: false,
        formOpen: true,
        deletePending: false,
      }),
    ).toBe(true);
    expect(
      modelProfileActionsLocked({
        loading: false,
        loadFailed: false,
        formOpen: false,
        deletePending: true,
      }),
    ).toBe(true);
    expect(
      modelProfileListHidden({ formOpen: false, deletePending: true }),
    ).toBe(true);
    expect(
      modelProfileListHidden({ formOpen: false, deletePending: false }),
    ).toBe(false);
  });
});

describe("buildModelWriteRequest", () => {
  it("omits blank credentials while editing", () => {
    const request = buildModelWriteRequest(editValue, { mode: "edit" });

    expect(request).not.toHaveProperty("api_key");
    expect(request).not.toHaveProperty("embedding_api_key");
  });

  it("sends null only for explicit credential clearing", () => {
    const request = buildModelWriteRequest(
      { ...editValue, clearApiKey: true },
      { mode: "edit" },
    );

    expect(request.api_key).toBeNull();
  });

  it("clears the full embedding group when editing disables it", () => {
    const request = buildModelWriteRequest(
      { ...editValue, embeddingEnabled: false },
      { mode: "edit", hadEmbedding: true },
    );

    expect(request).toMatchObject({
      embedding_base_url: null,
      embedding_model: null,
      embedding_dimension: null,
      embedding_api_key: null,
    });
  });
});

describe("response parsing", () => {
  it("whitelists response fields", () => {
    const parsed = parseModelProfileResponse({
      ...validResponse,
      api_key: "sentinel-secret",
    });

    expect(parsed).toEqual(validResponse);
    expect(parsed).not.toHaveProperty("api_key");
  });

  it("rejects an invalid success response without exposing its body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ api_key: "sentinel-secret" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(listModelProfiles()).rejects.toSatisfy((error: unknown) => {
      return (
        error instanceof ProfileApiError &&
        error.message === "Received an invalid model profile response." &&
        !error.message.includes("sentinel-secret")
      );
    });
  });
});

describe("profile API client", () => {
  it("sends a create request and returns the parsed profile", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ...validResponse, api_key: "sentinel-secret" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const profile = await createModelProfile(
      buildModelWriteRequest({ ...editValue, apiKey: "current-key" }, { mode: "create" }),
    );

    expect(profile).toEqual(validResponse);
    expect(profile).not.toHaveProperty("api_key");
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/local/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: "local-model",
        name: "Local model",
        provider_type: "openai_compatible",
        base_url: "http://localhost:11434/v1",
        model_name: "qwen2.5-coder",
        api_key: "current-key",
      }),
    });
  });

  it("uses the current form fields for a connection test without saved credentials", () => {
    expect(buildModelTestRequest(editValue)).toEqual({
      provider_type: "openai_compatible",
      base_url: "http://localhost:11434/v1",
      model_name: "qwen2.5-coder",
    });
  });

  it("keeps a structured backend error ahead of 422 mapping while discarding unexpected secret-like fields", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              code: "PROFILE_NOT_FOUND",
              message: "The model profile does not exist.",
              api_key: "sentinel-secret",
            },
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(listModelProfiles()).rejects.toSatisfy((error: unknown) => {
      return (
        error instanceof ProfileApiError &&
        error.code === "PROFILE_NOT_FOUND" &&
        error.message === "The model profile does not exist." &&
        !JSON.stringify(error).includes("sentinel-secret")
      );
    });
  });

  it.each([
    [
      "create",
      () =>
        createModelProfile(
          buildModelWriteRequest(editValue, { mode: "create" }),
        ),
    ],
    [
      "replace",
      () =>
        replaceModelProfile(
          editValue.id,
          buildModelWriteRequest(editValue, { mode: "edit" }),
        ),
    ],
    [
      "connection test",
      () => testModelConnection(buildModelTestRequest(editValue)),
    ],
  ])(
    "maps a FastAPI 422 array from %s to one stable error without leaking validation input",
    async (_operation, request) => {
      const sentinel = "https://sentinel-private-endpoint.example.test/v1";
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          Response.json(
            {
              detail: [
                {
                  type: "url_parsing",
                  loc: ["body", "base_url"],
                  msg: `Input should be a valid URL: ${sentinel}`,
                  input: sentinel,
                },
              ],
            },
            { status: 422 },
          ),
        ),
      );

      await expect(request()).rejects.toSatisfy((error: unknown) => {
        return (
          error instanceof ProfileApiError &&
          error.code === "PROFILE_VALIDATION_ERROR" &&
          error.message === "模型配置校验失败，请检查填写内容。" &&
          !`${error.code} ${error.message}`.includes(sentinel)
        );
      });
    },
  );
});

function createModelValue(
  profile: ModelProfileResponse,
): ModelProfileFormValue {
  return {
    id: profile.id,
    name: profile.name,
    baseUrl: profile.base_url,
    modelName: profile.model_name,
    apiKey: "",
    clearApiKey: false,
    embeddingEnabled: profile.embedding_base_url !== null,
    embeddingBaseUrl: profile.embedding_base_url ?? "",
    embeddingModel: profile.embedding_model ?? "",
    embeddingDimension: profile.embedding_dimension?.toString() ?? "",
    embeddingApiKey: "",
    clearEmbeddingApiKey: false,
  };
}
