import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ProfileApiError,
  buildModelTestRequest,
  buildModelWriteRequest,
  createModelProfile,
  listModelProfiles,
  parseModelProfileResponse,
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

afterEach(() => {
  vi.unstubAllGlobals();
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

  it("keeps stable backend errors while discarding unexpected secret-like fields", async () => {
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
          { status: 404, headers: { "Content-Type": "application/json" } },
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
});
