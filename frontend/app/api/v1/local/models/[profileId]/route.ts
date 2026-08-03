import { forwardBackendJson } from "@/lib/server/backend-json";

type RouteContext = { params: Promise<{ profileId: string }> };

function backendOptions(method: "GET" | "PUT" | "DELETE") {
  return {
    method,
    backendUrl: process.env.TEXT_TO_SQL_API_URL,
    apiKey: process.env.TEXT_TO_SQL_API_KEY,
  };
}

async function modelPath(context: RouteContext): Promise<string> {
  const { profileId } = await context.params;
  return `/api/v1/local/models/${encodeURIComponent(profileId)}`;
}

export async function GET(request: Request, context: RouteContext) {
  return forwardBackendJson(await modelPath(context), request, backendOptions("GET"));
}

export async function PUT(request: Request, context: RouteContext) {
  return forwardBackendJson(await modelPath(context), request, backendOptions("PUT"));
}

export async function DELETE(request: Request, context: RouteContext) {
  return forwardBackendJson(
    await modelPath(context),
    request,
    backendOptions("DELETE"),
  );
}
