import { describe, expect, it } from "vitest";

import type { StoredDbConfig } from "@/lib/types";
import { buildWorkbenchQueryRequest } from "./Workbench";

describe("Workbench query request", () => {
  it("builds only the retained datasource override path", () => {
    const dbConfig: StoredDbConfig = {
      version: 1,
      datasource_id: "local-postgres",
      type: "postgresql",
      connection: {
        mode: "form",
        host: "localhost",
        port: 5432,
        database: "pagila",
        username: "postgres",
        password: "database-secret",
      },
      auth: {
        schemas: ["public"],
        allowed_tables: ["public.film"],
      },
      updatedAt: "2026-08-03T00:00:00.000Z",
    };

    const request = buildWorkbenchQueryRequest("列出电影", dbConfig);

    expect(request).toEqual({
      question: "列出电影",
      datasource_id: "local-postgres",
      debug: false,
      datasource_override: {
        host: "localhost",
        port: 5432,
        database: "pagila",
        username: "postgres",
        password: "database-secret",
        type: "postgresql",
        schemas: ["public"],
        allowed_tables: ["public.film"],
      },
    });
  });
});
