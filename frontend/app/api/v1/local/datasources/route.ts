import { forwardBackendJson } from "@/lib/server/backend-json";

function options(method: "GET" | "POST") {
  return {
    method,
    backendUrl: process.env.TEXT_TO_SQL_API_URL,
    apiKey: process.env.TEXT_TO_SQL_API_KEY,
  };
}

export function GET(request: Request) {
  return forwardBackendJson("/api/v1/local/datasources", request, options("GET"));
}

export function POST(request: Request) {
  return forwardBackendJson("/api/v1/local/datasources", request, options("POST"));
}
