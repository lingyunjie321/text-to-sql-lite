import { forwardBackendJson } from "@/lib/server/backend-json";

type RouteContext = { params: Promise<{ profileId: string }> };

async function path(context: RouteContext): Promise<string> {
  const { profileId } = await context.params;
  return `/api/v1/local/datasources/${encodeURIComponent(profileId)}`;
}

function options(method: "GET" | "PUT" | "DELETE") {
  return {
    method,
    backendUrl: process.env.TEXT_TO_SQL_API_URL,
    apiKey: process.env.TEXT_TO_SQL_API_KEY,
  };
}

export async function GET(request: Request, context: RouteContext) {
  return forwardBackendJson(await path(context), request, options("GET"));
}

export async function PUT(request: Request, context: RouteContext) {
  return forwardBackendJson(await path(context), request, options("PUT"));
}

export async function DELETE(request: Request, context: RouteContext) {
  return forwardBackendJson(await path(context), request, options("DELETE"));
}
