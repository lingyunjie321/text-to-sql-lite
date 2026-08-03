import { forwardBackendJson } from "@/lib/server/backend-json";

export async function POST(request: Request) {
  return forwardBackendJson("/api/v1/local/models/test", request, {
    method: "POST",
    backendUrl: process.env.TEXT_TO_SQL_API_URL,
    apiKey: process.env.TEXT_TO_SQL_API_KEY,
  });
}
