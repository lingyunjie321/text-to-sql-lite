import { afterEach, describe, expect, it, vi } from "vitest";

import * as collectionRoute from "./route";
import * as testRoute from "./test/route";
import * as itemRoute from "./[profileId]/route";
import * as metadataRoute from "./[profileId]/metadata/route";

const backendUrl = "http://127.0.0.1:8000";
const profile = {
  id: "local-postgres",
  name: "Local PostgreSQL",
  database_type: "postgresql",
  host: "localhost",
  port: 5432,
  database: "pagila",
  username: "postgres",
  allowed_schemas: ["public"],
  allowed_tables: ["public.actor"],
  password_status: "configured",
};

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("datasource BFF routes", () => {
  it("forwards list, test, create, update, delete, and metadata operations", async () => {
    vi.stubEnv("TEXT_TO_SQL_API_URL", backendUrl);
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async (_input, init) => {
      if (init?.method === "DELETE") return new Response(null, { status: 204 });
      return Response.json(init?.method === "GET" ? [profile] : profile);
    });
    vi.stubGlobal("fetch", fetchMock);
    const jsonRequest = (path: string, method: "POST" | "PUT") =>
      new Request(`http://localhost${path}`, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profile),
      });
    const getRequest = (path: string) => new Request(`http://localhost${path}`);
    const context = { params: Promise.resolve({ profileId: profile.id }) };

    await collectionRoute.GET(getRequest("/api/v1/local/datasources"));
    await testRoute.POST(
      jsonRequest("/api/v1/local/datasources/test", "POST"),
    );
    await collectionRoute.POST(
      jsonRequest("/api/v1/local/datasources", "POST"),
    );
    await itemRoute.PUT(
      jsonRequest(`/api/v1/local/datasources/${profile.id}`, "PUT"),
      context,
    );
    await metadataRoute.GET(
      getRequest(`/api/v1/local/datasources/${profile.id}/metadata`),
      context,
    );
    const deleted = await itemRoute.DELETE(
      getRequest(`/api/v1/local/datasources/${profile.id}`),
      context,
    );

    expect(deleted.status).toBe(204);
    expect(fetchMock.mock.calls.map(([path, init]) => [path, init?.method])).toEqual([
      [`${backendUrl}/api/v1/local/datasources`, "GET"],
      [`${backendUrl}/api/v1/local/datasources/test`, "POST"],
      [`${backendUrl}/api/v1/local/datasources`, "POST"],
      [`${backendUrl}/api/v1/local/datasources/local-postgres`, "PUT"],
      [`${backendUrl}/api/v1/local/datasources/local-postgres/metadata`, "GET"],
      [`${backendUrl}/api/v1/local/datasources/local-postgres`, "DELETE"],
    ]);
  });
});
