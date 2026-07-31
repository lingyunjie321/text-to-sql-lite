import type {
  DatasourceOverride,
  ModelEndpointOverride,
  QueryRequest,
} from "./types";

/**
 * BFF 请求体白名单清洗。
 *
 * 后端 QueryRequest / ModelOverride / DatasourceOverride 均为 extra="forbid"，
 * 任何未声明字段（包括历史遗留的 model_config / datasource_config）都会导致 422。
 * 这里在转发前显式只保留契约字段，且只转发类型正确的值：
 * 类型不符的字段一律丢弃，由后端对缺失的必填字段（question）返回 422。
 */

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function pickString(
  source: Record<string, unknown>,
  key: string,
): string | undefined {
  const value = source[key];
  return typeof value === "string" ? value : undefined;
}

function pickStringArray(
  source: Record<string, unknown>,
  key: string,
): string[] | undefined {
  const value = source[key];
  if (!Array.isArray(value)) return undefined;
  return value.filter((item): item is string => typeof item === "string");
}

function assignIfDefined<T extends object, K extends keyof T>(
  target: T,
  key: K,
  value: T[K] | undefined,
): void {
  if (value !== undefined) {
    target[key] = value;
  }
}

/**
 * 清洗单个 ModelOverride（base_url/api_key/model_name，全部可选）。
 * 至少保留一个合法字段才返回该 tier，否则返回 undefined。
 */
function sanitizeModelEndpointOverride(
  value: unknown,
): ModelEndpointOverride | undefined {
  if (!isPlainObject(value)) return undefined;
  const result: ModelEndpointOverride = {};
  assignIfDefined(result, "base_url", pickString(value, "base_url"));
  assignIfDefined(result, "api_key", pickString(value, "api_key"));
  assignIfDefined(result, "model_name", pickString(value, "model_name"));
  return Object.keys(result).length > 0 ? result : undefined;
}

/**
 * 清洗 model_overrides（Record<tier, ModelOverride>）。
 * 剥离每个 tier 上的非法字段（如前端专用的 enabled）；无任何有效 tier 时返回 undefined。
 */
export function sanitizeModelOverrides(
  value: unknown,
): Record<string, ModelEndpointOverride> | undefined {
  if (!isPlainObject(value)) return undefined;
  const result: Record<string, ModelEndpointOverride> = {};
  for (const [tier, endpoint] of Object.entries(value)) {
    const sanitized = sanitizeModelEndpointOverride(endpoint);
    if (sanitized) {
      result[tier] = sanitized;
    }
  }
  return Object.keys(result).length > 0 ? result : undefined;
}

/**
 * 清洗 datasource_override（datasource_id/type/host/port/database/username/
 * password/schemas/allowed_tables，全部可选）。无任何有效字段时返回 undefined。
 */
export function sanitizeDatasourceOverride(
  value: unknown,
): DatasourceOverride | undefined {
  if (!isPlainObject(value)) return undefined;
  const result: DatasourceOverride = {};
  assignIfDefined(result, "datasource_id", pickString(value, "datasource_id"));
  assignIfDefined(result, "type", pickString(value, "type"));
  assignIfDefined(result, "host", pickString(value, "host"));
  assignIfDefined(result, "database", pickString(value, "database"));
  assignIfDefined(result, "username", pickString(value, "username"));
  assignIfDefined(result, "password", pickString(value, "password"));
  const port = value["port"];
  if (typeof port === "number" && Number.isInteger(port)) {
    result.port = port;
  }
  assignIfDefined(result, "schemas", pickStringArray(value, "schemas"));
  assignIfDefined(
    result,
    "allowed_tables",
    pickStringArray(value, "allowed_tables"),
  );
  return Object.keys(result).length > 0 ? result : undefined;
}

/**
 * 清洗转发给后端的 text-to-sql 请求体。
 * 仅保留 question/datasource_id/schemas/debug/model_overrides/datasource_override
 * 六个契约字段，其余一律丢弃。
 */
export function sanitizeQueryRequest(body: unknown): Partial<QueryRequest> {
  if (!isPlainObject(body)) return {};
  const result: Partial<QueryRequest> = {};
  assignIfDefined(result, "question", pickString(body, "question"));
  assignIfDefined(result, "datasource_id", pickString(body, "datasource_id"));
  assignIfDefined(result, "schemas", pickStringArray(body, "schemas"));
  const debug = body["debug"];
  if (typeof debug === "boolean") {
    result.debug = debug;
  }
  assignIfDefined(
    result,
    "model_overrides",
    sanitizeModelOverrides(body["model_overrides"]),
  );
  assignIfDefined(
    result,
    "datasource_override",
    sanitizeDatasourceOverride(body["datasource_override"]),
  );
  return result;
}
