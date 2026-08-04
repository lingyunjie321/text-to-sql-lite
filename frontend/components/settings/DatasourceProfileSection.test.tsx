import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { DatasourceProfileResponse } from "@/lib/datasource-profiles";
import {
  DatasourceProfileForm,
  DatasourceSchemaTree,
} from "./DatasourceProfileForm";
import { deleteDatasourceProfileFromState } from "./datasource-profile-coordinator";

const profile: DatasourceProfileResponse = {
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

describe("DatasourceProfileForm", () => {
  it("offers only PostgreSQL and MySQL and keeps the password transient", () => {
    const markup = renderToStaticMarkup(
      <DatasourceProfileForm
        mode="create"
        onSaved={() => undefined}
        onCancel={() => undefined}
      />,
    );

    expect(markup).toContain("PostgreSQL");
    expect(markup).toContain("MySQL");
    expect(markup).not.toContain("StarRocks");
    expect(markup).toContain('autoComplete="new-password"');
    expect(markup).not.toContain("DSN");
  });

  it("shows schema, table, view, and columns without auto-selecting metadata", () => {
    const markup = renderToStaticMarkup(
      <DatasourceSchemaTree
        schemas={[
          {
            name: "public",
            relations: [
              {
                name: "actor",
                kind: "table",
                columns: [
                  { name: "actor_id", data_type: "integer", nullable: false },
                ],
                primary_key: ["actor_id"],
              },
              { name: "film_list", kind: "view", columns: [], primary_key: [] },
            ],
          },
        ]}
        selectedTables={[]}
        onToggle={() => undefined}
      />,
    );

    expect(markup).toContain("public");
    expect(markup).toContain("actor");
    expect(markup).toContain("film_list");
    expect(markup).toContain("actor_id");
    expect(markup).toContain("视图");
    expect(markup).not.toContain('checked=""');
  });
});

describe("DatasourceProfile deletion", () => {
  it("clears the current selection when the current Profile is deleted", async () => {
    let cleared = false;
    const result = await deleteDatasourceProfileFromState([profile], profile.id, {
      deleteProfile: async () => undefined,
      getSelectedId: () => profile.id,
      clearSelectedId: () => {
        cleared = true;
      },
    });

    expect(result).toEqual({ profiles: [], selectedId: null });
    expect(cleared).toBe(true);
  });
});
