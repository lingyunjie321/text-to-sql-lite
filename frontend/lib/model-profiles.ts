export interface ModelProfileResponse {
  id: string;
  name: string;
  provider_type: "openai_compatible";
  base_url: string;
  model_name: string;
  embedding_base_url: string | null;
  embedding_model: string | null;
  embedding_dimension: number | null;
  generation_credential_status: "configured" | "missing";
  embedding_credential_status: "configured" | "missing" | "not_applicable";
}

export interface ModelProfileWriteRequest {
  id: string;
  name: string;
  provider_type: "openai_compatible";
  base_url: string;
  model_name: string;
  embedding_base_url?: string | null;
  embedding_model?: string | null;
  embedding_dimension?: number | null;
  api_key?: string | null;
  embedding_api_key?: string | null;
}

export interface ModelProfileFormValue {
  id: string;
  name: string;
  baseUrl: string;
  modelName: string;
  apiKey: string;
  clearApiKey: boolean;
  embeddingEnabled: boolean;
  embeddingBaseUrl: string;
  embeddingModel: string;
  embeddingDimension: string | number;
  embeddingApiKey: string;
  clearEmbeddingApiKey: boolean;
}

export interface ModelConnectionTestRequest {
  provider_type: "openai_compatible";
  base_url: string;
  model_name: string;
  embedding_base_url?: string;
  embedding_model?: string;
  embedding_dimension?: number;
  api_key?: string;
  embedding_api_key?: string;
}

export interface ModelConnectionTestResponse {
  generation: "connected";
  embedding: "connected" | "not_configured" | "unavailable";
  embedding_error: { code: string; message: string } | null;
}

export class ProfileApiError extends Error {
  readonly code: string;

  constructor(
    message = "Unable to complete model profile request.",
    code = "PROFILE_API_ERROR",
  ) {
    super(message);
    this.name = "ProfileApiError";
    this.code = code;
  }
}

type ModelWriteOptions = {
  mode: "create" | "edit";
  hadEmbedding?: boolean;
};

type JsonParser<T> = (value: unknown) => T;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isNullableString(value: unknown): value is string | null {
  return value === null || isString(value);
}

function isNullableInteger(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isInteger(value));
}

function isBlank(value: string): boolean {
  return value.trim() === "";
}

function parseDimension(value: string | number): number | undefined {
  if (typeof value === "number") {
    return Number.isInteger(value) ? value : undefined;
  }
  if (isBlank(value)) return undefined;
  const dimension = Number(value);
  return Number.isInteger(dimension) ? dimension : undefined;
}

function addCredential(
  request: ModelProfileWriteRequest,
  field: "api_key" | "embedding_api_key",
  value: string,
  shouldClear: boolean,
): void {
  if (shouldClear) {
    request[field] = null;
  } else if (!isBlank(value)) {
    request[field] = value;
  }
}

export function buildModelWriteRequest(
  value: ModelProfileFormValue,
  options: ModelWriteOptions,
): ModelProfileWriteRequest {
  const request: ModelProfileWriteRequest = {
    id: value.id,
    name: value.name,
    provider_type: "openai_compatible",
    base_url: value.baseUrl,
    model_name: value.modelName,
  };

  if (value.embeddingEnabled) {
    request.embedding_base_url = value.embeddingBaseUrl;
    request.embedding_model = value.embeddingModel;
    const dimension = parseDimension(value.embeddingDimension);
    if (dimension !== undefined) request.embedding_dimension = dimension;
    addCredential(
      request,
      "embedding_api_key",
      value.embeddingApiKey,
      value.clearEmbeddingApiKey,
    );
  } else if (options.mode === "edit" && options.hadEmbedding) {
    request.embedding_base_url = null;
    request.embedding_model = null;
    request.embedding_dimension = null;
    request.embedding_api_key = null;
  }

  addCredential(request, "api_key", value.apiKey, value.clearApiKey);
  return request;
}

export function buildModelTestRequest(
  value: ModelProfileFormValue,
): ModelConnectionTestRequest {
  const request: ModelConnectionTestRequest = {
    provider_type: "openai_compatible",
    base_url: value.baseUrl,
    model_name: value.modelName,
  };

  if (value.embeddingEnabled) {
    request.embedding_base_url = value.embeddingBaseUrl;
    request.embedding_model = value.embeddingModel;
    const dimension = parseDimension(value.embeddingDimension);
    if (dimension !== undefined) request.embedding_dimension = dimension;
    if (!isBlank(value.embeddingApiKey)) {
      request.embedding_api_key = value.embeddingApiKey;
    }
  }
  if (!isBlank(value.apiKey)) request.api_key = value.apiKey;
  return request;
}

export function parseModelProfileResponse(value: unknown): ModelProfileResponse {
  if (!isRecord(value)) throw invalidResponseError();

  const {
    id,
    name,
    provider_type,
    base_url,
    model_name,
    embedding_base_url,
    embedding_model,
    embedding_dimension,
    generation_credential_status,
    embedding_credential_status,
  } = value;

  if (
    !isString(id) ||
    !isString(name) ||
    provider_type !== "openai_compatible" ||
    !isString(base_url) ||
    !isString(model_name) ||
    !isNullableString(embedding_base_url) ||
    !isNullableString(embedding_model) ||
    !isNullableInteger(embedding_dimension) ||
    (generation_credential_status !== "configured" &&
      generation_credential_status !== "missing") ||
    (embedding_credential_status !== "configured" &&
      embedding_credential_status !== "missing" &&
      embedding_credential_status !== "not_applicable")
  ) {
    throw invalidResponseError();
  }

  return {
    id,
    name,
    provider_type,
    base_url,
    model_name,
    embedding_base_url,
    embedding_model,
    embedding_dimension,
    generation_credential_status,
    embedding_credential_status,
  };
}

function parseModelConnectionTestResponse(value: unknown): ModelConnectionTestResponse {
  if (!isRecord(value) || value.generation !== "connected") {
    throw invalidResponseError();
  }
  if (
    value.embedding !== "connected" &&
    value.embedding !== "not_configured" &&
    value.embedding !== "unavailable"
  ) {
    throw invalidResponseError();
  }

  let embeddingError: ModelConnectionTestResponse["embedding_error"] = null;
  if (value.embedding_error !== null) {
    if (
      !isRecord(value.embedding_error) ||
      !isString(value.embedding_error.code) ||
      !isString(value.embedding_error.message)
    ) {
      throw invalidResponseError();
    }
    embeddingError = {
      code: value.embedding_error.code,
      message: value.embedding_error.message,
    };
  }

  return {
    generation: "connected",
    embedding: value.embedding,
    embedding_error: embeddingError,
  };
}

function invalidResponseError(): ProfileApiError {
  return new ProfileApiError(
    "Received an invalid model profile response.",
    "PROFILE_API_INVALID_RESPONSE",
  );
}

async function readJson(response: Response): Promise<unknown | undefined> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

function parseError(value: unknown, status: number): ProfileApiError {
  if (
    isRecord(value) &&
    isRecord(value.detail) &&
    isString(value.detail.code) &&
    isString(value.detail.message)
  ) {
    return new ProfileApiError(value.detail.message, value.detail.code);
  }
  if (status === 422) {
    return new ProfileApiError(
      "模型配置校验失败，请检查填写内容。",
      "PROFILE_VALIDATION_ERROR",
    );
  }
  return new ProfileApiError();
}

export async function requestProfileApi<T>(
  path: string,
  init: RequestInit,
  parse: JsonParser<T>,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ProfileApiError();
  }

  const body = await readJson(response);
  if (!response.ok) throw parseError(body, response.status);
  if (body === undefined) throw invalidResponseError();
  return parse(body);
}

function json(method: "POST" | "PUT", body: object): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const listModelProfiles = () =>
  requestProfileApi<ModelProfileResponse[]>(
    "/api/v1/local/models",
    { method: "GET" },
    (value) => {
      if (!Array.isArray(value)) throw invalidResponseError();
      return value.map(parseModelProfileResponse);
    },
  );

export const createModelProfile = (body: ModelProfileWriteRequest) =>
  requestProfileApi<ModelProfileResponse>(
    "/api/v1/local/models",
    json("POST", body),
    parseModelProfileResponse,
  );

export const replaceModelProfile = (id: string, body: ModelProfileWriteRequest) =>
  requestProfileApi<ModelProfileResponse>(
    `/api/v1/local/models/${encodeURIComponent(id)}`,
    json("PUT", body),
    parseModelProfileResponse,
  );

export async function deleteModelProfile(id: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api/v1/local/models/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  } catch {
    throw new ProfileApiError();
  }

  if (response.status === 204) return;
  throw parseError(await readJson(response), response.status);
}

export const testModelConnection = (body: ModelConnectionTestRequest) =>
  requestProfileApi<ModelConnectionTestResponse>(
    "/api/v1/local/models/test",
    json("POST", body),
    parseModelConnectionTestResponse,
  );
