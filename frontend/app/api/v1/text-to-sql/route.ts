import { NextRequest, NextResponse } from "next/server";
import { sanitizeQueryRequest } from "@/lib/query-request";

const BACKEND_URL = process.env.TEXT_TO_SQL_API_URL;
const API_KEY = process.env.TEXT_TO_SQL_API_KEY;

export async function POST(request: NextRequest) {
  // Check if backend URL is configured
  if (!BACKEND_URL) {
    return NextResponse.json(
      {
        request_id: "unknown",
        trace_id: "unknown",
        status: "FAILED_INTERNAL",
        error: {
          error_type: "CONNECTION_ERROR",
          code: "BACKEND_NOT_CONFIGURED",
          message: "后端服务地址未配置。",
        },
      },
      { status: 200 },
    );
  }

  // Parse request body — malformed JSON gets a 400 instead of a misleading
  // "backend unreachable" error.
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      {
        request_id: "unknown",
        trace_id: "unknown",
        status: "FAILED_INTERNAL",
        error: {
          error_type: "UNKNOWN",
          code: "INVALID_JSON_BODY",
          message: "请求体不是合法的 JSON。",
        },
      },
      { status: 400 },
    );
  }

  try {
    // Whitelist-strip the body to the backend QueryRequest contract. Everything
    // else — including legacy model_config / datasource_config — is dropped to
    // avoid 422 (extra="forbid").
    const cleanBody = sanitizeQueryRequest(body);

    // Phase 4a: Build headers with optional API key injection
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (API_KEY) {
      headers["Authorization"] = `Bearer ${API_KEY}`;
    }

    const response = await fetch(
      `${BACKEND_URL}/api/v1/text-to-sql`,
      {
        method: "POST",
        headers,
        body: JSON.stringify(cleanBody),
      },
    );

    // Try to parse the response body
    let data;
    try {
      data = await response.json();
    } catch {
      data = {
        request_id: "unknown",
        trace_id: "unknown",
        status: "FAILED_INTERNAL",
        error: {
          error_type: "UNKNOWN",
          code: "RESPONSE_PARSE_ERROR",
          message: "无法解析后端响应。",
        },
      };
    }

    return NextResponse.json(data, { status: response.status });
  } catch {
    // Network error — backend unreachable
    return NextResponse.json(
      {
        request_id: "unknown",
        trace_id: "unknown",
        status: "FAILED_INTERNAL",
        error: {
          error_type: "CONNECTION_ERROR",
          code: "BACKEND_UNREACHABLE",
          message: "无法连接到后端服务，请稍后重试。",
        },
      },
      { status: 200 },
    );
  }
}
