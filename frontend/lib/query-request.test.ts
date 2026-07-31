import { describe, expect, it } from "vitest";
import {
  sanitizeDatasourceOverride,
  sanitizeModelOverrides,
  sanitizeQueryRequest,
} from "./query-request";

describe("sanitizeQueryRequest", () => {
  it("keeps all six contract fields when well-typed", () => {
    const result = sanitizeQueryRequest({
      question: "列出所有演员",
      datasource_id: "pagila",
      schemas: ["public"],
      debug: true,
      model_overrides: {
        simple: { base_url: "https://x", api_key: "k", model_name: "m" },
      },
      datasource_override: { host: "db.local", port: 5432 },
    });
    expect(result).toEqual({
      question: "列出所有演员",
      datasource_id: "pagila",
      schemas: ["public"],
      debug: true,
      model_overrides: {
        simple: { base_url: "https://x", api_key: "k", model_name: "m" },
      },
      datasource_override: { host: "db.local", port: 5432 },
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

  it("filters non-string elements out of schemas arrays", () => {
    const result = sanitizeQueryRequest({
      question: "q",
      schemas: ["public", 42, null, "sales"],
    });
    expect(result.schemas).toEqual(["public", "sales"]);
  });

  it("returns an empty object for non-object bodies", () => {
    expect(sanitizeQueryRequest(null)).toEqual({});
    expect(sanitizeQueryRequest("not json object")).toEqual({});
    expect(sanitizeQueryRequest([1, 2, 3])).toEqual({});
    expect(sanitizeQueryRequest(undefined)).toEqual({});
  });

  it("omits override keys entirely when they sanitize to nothing", () => {
    const result = sanitizeQueryRequest({
      question: "q",
      model_overrides: "not-an-object",
      datasource_override: {},
    });
    expect("model_overrides" in result).toBe(false);
    expect("datasource_override" in result).toBe(false);
  });
});

describe("sanitizeModelOverrides", () => {
  it("strips frontend-only fields like enabled from each tier", () => {
    const result = sanitizeModelOverrides({
      simple: {
        base_url: "https://api.example.com",
        api_key: "sk-xxx",
        model_name: "gpt-4o-mini",
        enabled: true,
      },
    });
    expect(result).toEqual({
      simple: {
        base_url: "https://api.example.com",
        api_key: "sk-xxx",
        model_name: "gpt-4o-mini",
      },
    });
  });

  it("keeps tiers with partial fields (backend ModelOverride is all-optional)", () => {
    const result = sanitizeModelOverrides({
      complex: { model_name: "o1" },
    });
    expect(result).toEqual({ complex: { model_name: "o1" } });
  });

  it("drops tiers that have no valid fields or are not objects", () => {
    const result = sanitizeModelOverrides({
      simple: { enabled: true, base_url: 42 },
      standard: null,
      complex: "oops",
      fallback: { api_key: "k" },
    });
    expect(result).toEqual({ fallback: { api_key: "k" } });
  });

  it("returns undefined when nothing survives", () => {
    expect(sanitizeModelOverrides({ simple: { enabled: true } })).toBeUndefined();
    expect(sanitizeModelOverrides("junk")).toBeUndefined();
    expect(sanitizeModelOverrides(undefined)).toBeUndefined();
  });
});

describe("sanitizeDatasourceOverride", () => {
  it("keeps all nine contract fields", () => {
    const input = {
      datasource_id: "my-db",
      type: "postgresql",
      host: "db.local",
      port: 5432,
      database: "pagila",
      username: "postgres",
      password: "secret",
      schemas: ["public"],
      allowed_tables: ["film", "actor"],
    };
    expect(sanitizeDatasourceOverride(input)).toEqual(input);
  });

  it("strips unknown fields (extra=forbid protection)", () => {
    const result = sanitizeDatasourceOverride({
      host: "db.local",
      dsn: "postgresql://u:p@h:5432/db",
      mode: "form",
    });
    expect(result).toEqual({ host: "db.local" });
  });

  it("accepts only integer ports", () => {
    expect(sanitizeDatasourceOverride({ port: 5432 })).toEqual({ port: 5432 });
    expect(sanitizeDatasourceOverride({ port: "5432" })).toBeUndefined();
    expect(sanitizeDatasourceOverride({ port: 5432.5 })).toBeUndefined();
  });

  it("filters non-string elements from schemas and allowed_tables", () => {
    const result = sanitizeDatasourceOverride({
      schemas: ["public", 1],
      allowed_tables: [],
    });
    expect(result).toEqual({ schemas: ["public"], allowed_tables: [] });
  });

  it("returns undefined for non-objects or when nothing survives", () => {
    expect(sanitizeDatasourceOverride(null)).toBeUndefined();
    expect(sanitizeDatasourceOverride("dsn-string")).toBeUndefined();
    expect(sanitizeDatasourceOverride({ unknown: 1 })).toBeUndefined();
  });
});
