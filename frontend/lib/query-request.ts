import type { QueryRequest } from "./types";

/**
 * BFF 请求体白名单清洗。
 *
 * 后端 QueryRequest 为 extra="forbid"，任何未声明字段都会导致 422。
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
 * 清洗转发给后端的 text-to-sql 请求体。
 * 普通浏览器查询只允许 Profile 模式的四个字段。
 */
export function sanitizeQueryRequest(body: unknown): Partial<QueryRequest> {
  if (!isPlainObject(body)) return {};
  const result: Partial<QueryRequest> = {};
  assignIfDefined(result, "question", pickString(body, "question"));
  assignIfDefined(result, "datasource_id", pickString(body, "datasource_id"));
  assignIfDefined(
    result,
    "model_profile_id",
    pickString(body, "model_profile_id"),
  );
  const debug = body["debug"];
  if (typeof debug === "boolean") {
    result.debug = debug;
  }
  return result;
}
