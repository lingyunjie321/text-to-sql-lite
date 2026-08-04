import { forwardBackendJson } from "@/lib/server/backend-json";

export function POST(request: Request) {
  return forwardBackendJson("/api/v1/local/datasources/test", request, {
    method: "POST",
    backendUrl: process.env.TEXT_TO_SQL_API_URL,
    apiKey: process.env.TEXT_TO_SQL_API_KEY,
  });
}
