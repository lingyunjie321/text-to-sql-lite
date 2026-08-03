import { forwardBackendJson } from "@/lib/server/backend-json";

function backendOptions(method: "GET" | "POST") {
  return {
    method,
    backendUrl: process.env.TEXT_TO_SQL_API_URL,
    apiKey: process.env.TEXT_TO_SQL_API_KEY,
  };
}

export async function GET(request: Request) {
  return forwardBackendJson(
    "/api/v1/local/models",
    request,
    backendOptions("GET"),
  );
}

export async function POST(request: Request) {
  return forwardBackendJson(
    "/api/v1/local/models",
    request,
    backendOptions("POST"),
  );
}
