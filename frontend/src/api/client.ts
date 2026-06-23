import type {
  DialectName,
  QueryRunResponse,
  RuntimeConfigCreateRequest,
  RuntimeConfigResponse,
  RuntimeOptionsResponse,
  SchemaResponse
} from "./types";

export interface RunQueryRequest {
  question: string;
  targetDialect: DialectName;
  runtimeConfigId?: string | null;
}

export interface RunEditedSqlRequest {
  sql: string;
  targetDialect: DialectName;
  runtimeConfigId?: string | null;
}

export interface TextToSqlClient {
  getSchema: (runtimeConfigId?: string | null) => Promise<SchemaResponse>;
  getRuntimeOptions: () => Promise<RuntimeOptionsResponse>;
  createRuntimeConfig: (request: RuntimeConfigCreateRequest) => Promise<RuntimeConfigResponse>;
  runQuery: (request: RunQueryRequest) => Promise<QueryRunResponse>;
  runEditedSql: (request: RunEditedSqlRequest) => Promise<QueryRunResponse>;
}

export class ApiClientError extends Error {
  readonly userMessage: string;
  readonly technicalDetails: unknown;

  constructor(message: string, userMessage: string, technicalDetails?: unknown) {
    super(message);
    this.name = "ApiClientError";
    this.userMessage = userMessage;
    this.technicalDetails = technicalDetails;
  }
}

export function createTextToSqlClient(baseUrl = ""): TextToSqlClient {
  return {
    getSchema: (runtimeConfigId) => {
      const query = runtimeConfigId ? `?runtime_config_id=${encodeURIComponent(runtimeConfigId)}` : "";
      return requestJson<SchemaResponse>(`${baseUrl}/api/v1/schema${query}`);
    },
    getRuntimeOptions: () => requestJson<RuntimeOptionsResponse>(`${baseUrl}/api/v1/runtime/options`),
    createRuntimeConfig: (request) =>
      requestJson<RuntimeConfigResponse>(`${baseUrl}/api/v1/runtime/configs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request)
      }),
    runQuery: (request) =>
      requestJson<QueryRunResponse>(`${baseUrl}/api/v1/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: request.question,
          target_dialect: request.targetDialect,
          max_attempts: 3,
          debug: true,
          runtime_config_id: request.runtimeConfigId ?? null
        })
      }),
    runEditedSql: (request) =>
      requestJson<QueryRunResponse>(`${baseUrl}/api/v1/sql/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sql: request.sql,
          target_dialect: request.targetDialect,
          max_rows: 100,
          runtime_config_id: request.runtimeConfigId ?? null
        })
      })
  };
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const payload = await readJson(response);
  if (!response.ok) {
    const apiError = toApiError(payload);
    throw new ApiClientError(
      apiError?.error.message ?? `HTTP ${response.status}`,
      apiError?.error.message ?? "请求失败，请稍后重试。",
      payload
    );
  }
  return payload as T;
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new ApiClientError(
      "响应不是合法 JSON",
      "服务返回了无法读取的响应。",
      error instanceof Error ? error.message : String(error)
    );
  }
}

function toApiError(payload: unknown): { error: { message: string } } | null {
  if (!payload || typeof payload !== "object" || !("error" in payload)) {
    return null;
  }
  const error = payload.error;
  if (!error || typeof error !== "object" || !("message" in error)) {
    return null;
  }
  const message = error.message;
  return typeof message === "string" ? { error: { message } } : null;
}
