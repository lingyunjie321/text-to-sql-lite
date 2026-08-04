import { NextResponse } from "next/server";

const BACKEND_URL = process.env.TEXT_TO_SQL_API_URL;

export async function GET() {
  if (!BACKEND_URL) {
    return NextResponse.json(
      { status: "unhealthy", message: "后端未配置" },
      { status: 503 },
    );
  }

  try {
    const res = await fetch(`${BACKEND_URL}/health`, { method: "GET" });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json(
      { status: "unhealthy", message: "后端不可达" },
      { status: 503 },
    );
  }
}
