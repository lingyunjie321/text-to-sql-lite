import { describe, expect, it } from "vitest";
import { sanitizeQueryRequest } from "./query-request";

describe("sanitizeQueryRequest", () => {
  it("keeps only the Profile query contract fields when well-typed", () => {
    const result = sanitizeQueryRequest({
      question: "列出所有演员",
      datasource_id: "pagila",
      debug: true,
      model_profile_id: "local-model",
      schemas: ["public"],
      model_overrides: {
        simple: { base_url: "https://x", api_key: "k", model_name: "m" },
      },
      datasource_override: { host: "db.local", port: 5432 },
    });
    expect(result).toEqual({
      question: "列出所有演员",
      datasource_id: "pagila",
      debug: true,
      model_profile_id: "local-model",
    });
  });

  it("drops legacy and unknown top-level fields (extra=forbid protection)", () => {
    const result = sanitizeQueryRequest({
      question: "q",
      model_config: { simple: {} },
      datasource_config: { host: "h" },
      hack: "unknown-field",
      __proto__: { polluted: true },
    });
    expect(result).toEqual({ question: "q" });
    expect("model_config" in result).toBe(false);
    expect("datasource_config" in result).toBe(false);
    expect("hack" in result).toBe(false);
  });

  it("drops fields with wrong types instead of forwarding them", () => {
    const result = sanitizeQueryRequest({
      question: 123,
      datasource_id: ["pagila"],
      debug: "true",
      schemas: "public",
    });
    expect(result).toEqual({});
    expect("question" in result).toBe(false);
    expect("debug" in result).toBe(false);
  });

  it("never forwards browser credentials, overrides, schemas, or allowlists", () => {
    const result = sanitizeQueryRequest({
      question: "q",
      model_profile_id: "local-model",
      schemas: ["public"],
      model_overrides: { simple: { api_key: "model-secret" } },
      datasource_override: {
        password: "database-secret",
        host: "localhost",
        allowed_tables: ["public.actor"],
      },
      dsn: "postgresql://user:secret@localhost/pagila",
    });
    expect(result).toEqual({ question: "q", model_profile_id: "local-model" });
    expect(JSON.stringify(result)).not.toContain("secret");
  });

  it("returns an empty object for non-object bodies", () => {
    expect(sanitizeQueryRequest(null)).toEqual({});
    expect(sanitizeQueryRequest("not json object")).toEqual({});
    expect(sanitizeQueryRequest([1, 2, 3])).toEqual({});
    expect(sanitizeQueryRequest(undefined)).toEqual({});
  });

});
