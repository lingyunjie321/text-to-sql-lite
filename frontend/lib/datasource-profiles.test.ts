import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildDatasourceWriteRequest,
  createDatasourceProfile,
  deleteDatasourceProfile,
  getDatasourceMetadata,
  listDatasourceProfiles,
  parseDatasourceMetadataResponse,
  parseDatasourceProfileResponse,
  replaceDatasourceProfile,
  testDatasourceConnection,
} from "./datasource-profiles";

const profile = {
  id: "local-postgres",
  name: "Local PostgreSQL",
  database_type: "postgresql" as const,
  host: "localhost",
  port: 5432,
  database: "pagila",
  username: "postgres",
  allowed_schemas: ["public"],
  allowed_tables: ["public.actor"],
  password_status: "configured" as const,
};

const limits = {
  timeout_seconds: 10,
  max_relations: 500,
  max_columns: 5000,
  max_foreign_keys: 1000,
};

afterEach(() => vi.unstubAllGlobals());

describe("DatasourceProfile response parsing", () => {
  it("accepts the exact backend Profile response without credentials", () => {
    expect(parseDatasourceProfileResponse(profile)).toEqual(profile);
    expect(parseDatasourceProfileResponse(profile)).not.toHaveProperty("password");
    expect(parseDatasourceProfileResponse(profile)).not.toHaveProperty("dsn");
  });

  it("rejects unsupported database types and malformed allowlists", () => {
    expect(() =>
      parseDatasourceProfileResponse({ ...profile, database_type: "starrocks" }),
    ).toThrow();
    expect(() =>
      parseDatasourceProfileResponse({ ...profile, allowed_tables: "public.actor" }),
    ).toThrow();
  });

  it("parses metadata columns without changing the saved allowlist", () => {
    const metadata = parseDatasourceMetadataResponse({
      datasource_id: profile.id,
      schemas: [
        {
          name: "public",
          relations: [
            {
              name: "actor",
              kind: "table",
              columns: [{ name: "actor_id", data_type: "integer", nullable: false }],
              primary_key: ["actor_id"],
            },
            { name: "film", kind: "view", columns: [], primary_key: [] },
          ],
        },
      ],
      foreign_keys: [],
      truncated: false,
      limits,
    });

    expect(metadata.schemas[0]?.relations[0]?.columns[0]?.name).toBe("actor_id");
    expect(profile.allowed_tables).toEqual(["public.actor"]);
  });
});

describe("DatasourceProfile request building", () => {
  it("includes only manually selected tables and never expands from metadata", () => {
    const request = buildDatasourceWriteRequest(
      {
        id: profile.id,
        name: profile.name,
        databaseType: "postgresql",
        host: "localhost",
        port: "5432",
        database: "pagila",
        username: "postgres",
        password: "database-secret",
        clearPassword: false,
        allowedTables: ["public.actor"],
      },
      { mode: "create" },
    );

    expect(request).toEqual({
      id: profile.id,
      name: profile.name,
      database_type: "postgresql",
      host: "localhost",
      port: 5432,
      database: "pagila",
      username: "postgres",
      allowed_schemas: ["public"],
      allowed_tables: ["public.actor"],
      password: "database-secret",
    });
    expect(JSON.stringify(request)).not.toContain("public.film");
  });

  it("keeps an explicit empty password for passwordless create connections", () => {
    const request = buildDatasourceWriteRequest(
      {
        id: profile.id,
        name: profile.name,
        databaseType: "postgresql",
        host: "localhost",
        port: 5432,
        database: "pagila",
        username: "postgres",
        password: "",
        clearPassword: false,
        allowedTables: ["public.actor"],
      },
      { mode: "create" },
    );

    expect(request.password).toBe("");
  });
});

describe("DatasourceProfile browser API", () => {
  it("uses list, test, create, update, delete, and metadata BFF endpoints", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async (input, init) => {
      const path = String(input);
      if (init?.method === "DELETE") return new Response(null, { status: 204 });
      if (path.endsWith("/test")) {
        return Response.json({
          status: "ok",
          schemas: ["public"],
          relations: [{ schema: "public", name: "actor", kind: "table" }],
          truncated: false,
          limits,
        });
      }
      if (path.endsWith("/metadata")) {
        return Response.json({
          datasource_id: profile.id,
          schemas: [],
          foreign_keys: [],
          truncated: false,
          limits,
        });
      }
      if (path === "/api/v1/local/datasources" && init?.method === "GET") {
        return Response.json([profile]);
      }
      return Response.json(profile, { status: init?.method === "POST" ? 201 : 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    await listDatasourceProfiles();
    await testDatasourceConnection({
      database_type: "postgresql",
      host: "localhost",
      port: 5432,
      database: "pagila",
      username: "postgres",
      password: "database-secret",
    });
    const write = { ...profile, password_status: undefined };
    delete write.password_status;
    await createDatasourceProfile(write);
    await replaceDatasourceProfile(profile.id, write);
    await getDatasourceMetadata(profile.id);
    await deleteDatasourceProfile(profile.id);

    expect(fetchMock.mock.calls.map(([path, init]) => [path, init?.method])).toEqual([
      ["/api/v1/local/datasources", "GET"],
      ["/api/v1/local/datasources/test", "POST"],
      ["/api/v1/local/datasources", "POST"],
      ["/api/v1/local/datasources/local-postgres", "PUT"],
      ["/api/v1/local/datasources/local-postgres/metadata", "GET"],
      ["/api/v1/local/datasources/local-postgres", "DELETE"],
    ]);
  });
});
