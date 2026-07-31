import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.TEXT_TO_SQL_API_URL;

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

  try {
    const body = await request.json();

    const response = await fetch(
      `${BACKEND_URL}/api/v1/text-to-sql`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
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
  } catch (error) {
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
