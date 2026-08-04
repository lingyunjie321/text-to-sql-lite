import { forwardBackendJson } from "@/lib/server/backend-json";

type ModelTestRouteMethod = "POST" | "GET" | "PUT" | "DELETE";

function backendOptions(method: ModelTestRouteMethod) {
  return {
    method,
    backendUrl: process.env.TEXT_TO_SQL_API_URL,
    apiKey: process.env.TEXT_TO_SQL_API_KEY,
  };
}

function forward(request: Request, method: ModelTestRouteMethod) {
  return forwardBackendJson(
    "/api/v1/local/models/test",
    request,
    backendOptions(method),
  );
}

export async function POST(request: Request) {
  return forward(request, "POST");
}

export async function GET(request: Request) {
  return forward(request, "GET");
}

export async function PUT(request: Request) {
  return forward(request, "PUT");
}

export async function DELETE(request: Request) {
  return forward(request, "DELETE");
}
