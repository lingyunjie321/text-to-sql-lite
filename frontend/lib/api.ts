import type {
  QueryRequest,
  QueryResponse,
} from "./types";

export async function queryTextToSql(
  request: QueryRequest,
): Promise<QueryResponse> {
  const res = await fetch("/api/v1/text-to-sql", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  // Try to parse JSON body regardless of status code
  let data: QueryResponse | null = null;
  try {
    data = (await res.json()) as QueryResponse;
  } catch {
    // JSON parse failed — construct a network-error response
    data = {
      request_id: "unknown",
      trace_id: "unknown",
      status: "FAILED_INTERNAL",
      error: {
        error_type: "UNKNOWN",
        code: "RESPONSE_PARSE_ERROR",
        message: "无法解析服务端响应。",
      },
    };
  }

  // If HTTP error and the body doesn't already have a valid status,
  // wrap it into a FAILED_INTERNAL shape
  if (!res.ok && data && !data.status) {
    data = {
      request_id: data.request_id || "unknown",
      trace_id: data.trace_id || "unknown",
      status: "FAILED_INTERNAL",
      error: {
        error_type: "UNKNOWN",
        code: `HTTP_${res.status}`,
        message: `服务端返回错误 (HTTP ${res.status})。`,
      },
    };
  }

  return data as QueryResponse;
}
