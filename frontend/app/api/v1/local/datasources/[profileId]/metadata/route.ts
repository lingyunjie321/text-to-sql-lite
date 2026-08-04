import { forwardBackendJson } from "@/lib/server/backend-json";

type RouteContext = { params: Promise<{ profileId: string }> };

export async function GET(request: Request, context: RouteContext) {
  const { profileId } = await context.params;
  return forwardBackendJson(
    `/api/v1/local/datasources/${encodeURIComponent(profileId)}/metadata`,
    request,
    {
      method: "GET",
      backendUrl: process.env.TEXT_TO_SQL_API_URL,
      apiKey: process.env.TEXT_TO_SQL_API_KEY,
    },
  );
}
