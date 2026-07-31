import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.TEXT_TO_SQL_API_URL;

export async function GET(_request: NextRequest) {
  if (!BACKEND_URL) {
    return NextResponse.json({ error: "后端未配置" }, { status: 503 });
  }

  try {
    const res = await fetch(`${BACKEND_URL}/api/v1/config`, { method: "GET" });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ error: "后端不可达" }, { status: 503 });
  }
}
