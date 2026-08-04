import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildDsn,
  clearDbConfig,
  DEFAULT_PORTS,
  getDbConfig,
  getDefaultDbConfig,
  isDbConfigured,
  parseDsn,
  setDbConfig,
} from "./datasource-config";

const STORAGE_KEY = "text-to-sql-db-config";

function createLocalStorageMock() {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
}

const localStorageMock = createLocalStorageMock();

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-08-04T00:00:00.000Z"));
  localStorageMock.clear();
  vi.stubGlobal("window", { localStorage: localStorageMock });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("getDbConfig", () => {
  it("returns pagila defaults when window is undefined (SSR)", () => {
    vi.unstubAllGlobals();
    const config = getDbConfig();
    expect(config.datasource_id).toBe("pagila");
    expect(config.type).toBe("postgresql");
    expect(config.connection.port).toBe(DEFAULT_PORTS.postgresql);
  });

  it("returns defaults when storage is empty or corrupted", () => {
    expect(getDbConfig()).toEqual(getDefaultDbConfig());
    localStorageMock.setItem(STORAGE_KEY, "[[[broken");
    expect(getDbConfig()).toEqual(getDefaultDbConfig());
  });

  it("returns defaults when stored version mismatches", () => {
    localStorageMock.setItem(
      STORAGE_KEY,
      JSON.stringify({ version: 2, datasource_id: "other" }),
    );
    expect(getDbConfig().datasource_id).toBe("pagila");
  });

  it("fills missing fields from defaults for partial stored configs", () => {
    localStorageMock.setItem(
      STORAGE_KEY,
      JSON.stringify({
        version: 1,
        datasource_id: "analytics",
        type: "mysql",
        connection: { host: "mysql.local" },
      }),
    );
    const config = getDbConfig();
    expect(config.datasource_id).toBe("analytics");
    expect(config.type).toBe("mysql");
    expect(config.connection.host).toBe("mysql.local");
    // port falls back to the default for the stored type
    expect(config.connection.port).toBe(DEFAULT_PORTS.mysql);
    // missing auth section gets empty lists
    expect(config.auth).toEqual({ schemas: [], allowed_tables: [] });
  });
});

describe("setDbConfig / clearDbConfig", () => {
  it("round-trips a config through localStorage", () => {
    const config = getDefaultDbConfig();
    config.datasource_id = "warehouse";
    config.auth.schemas = ["public", "sales"];
    setDbConfig(config);
    const loaded = getDbConfig();
    expect(loaded.datasource_id).toBe("warehouse");
    expect(loaded.auth.schemas).toEqual(["public", "sales"]);
  });

  it("clearDbConfig removes the stored value", () => {
    setDbConfig(getDefaultDbConfig());
    clearDbConfig();
    expect(localStorageMock.getItem(STORAGE_KEY)).toBeNull();
  });

  it("is a no-op when window is undefined", () => {
    vi.unstubAllGlobals();
    expect(() => setDbConfig(getDefaultDbConfig())).not.toThrow();
    expect(() => clearDbConfig()).not.toThrow();
  });
});

describe("parseDsn", () => {
  it("parses a standard postgresql DSN", () => {
    expect(parseDsn("postgresql://alice:s3cret@db.internal:5432/pagila")).toEqual({
      type: "postgresql",
      username: "alice",
      password: "s3cret",
      host: "db.internal",
      port: 5432,
      database: "pagila",
    });
  });

  it("parses mysql and starrocks DSNs", () => {
    expect(parseDsn("mysql://root:@127.0.0.1:3306/shop")?.type).toBe("mysql");
    expect(parseDsn("starrocks://u:p@sr:9030/olap")?.port).toBe(9030);
  });

  it("decodes percent-encoded credentials", () => {
    const parsed = parseDsn(
      "postgresql://user%40corp:p%40ss%2Fword@host:5432/db",
    );
    expect(parsed?.username).toBe("user@corp");
    expect(parsed?.password).toBe("p@ss/word");
  });

  it("returns null for malformed DSNs", () => {
    expect(parseDsn("not-a-dsn")).toBeNull();
    expect(parseDsn("oracle://u:p@h:1521/db")).toBeNull();
    expect(parseDsn("postgresql://u:p@host:notaport/db")).toBeNull();
  });
});

describe("buildDsn", () => {
  it("builds a DSN with encoded credentials", () => {
    expect(
      buildDsn({
        type: "postgresql",
        username: "user@corp",
        password: "p@ss",
        host: "db.local",
        port: 5432,
        database: "pagila",
      }),
    ).toBe("postgresql://user%40corp:p%40ss@db.local:5432/pagila");
  });

  it("returns an empty string when required fields are missing", () => {
    const base = {
      type: "mysql" as const,
      username: "u",
      password: "",
      host: "h",
      port: 3306,
      database: "d",
    };
    expect(buildDsn({ ...base, username: "" })).toBe("");
    expect(buildDsn({ ...base, host: "" })).toBe("");
    expect(buildDsn({ ...base, database: "" })).toBe("");
  });
});

describe("isDbConfigured", () => {
  it("is true for the default pagila form config", () => {
    expect(isDbConfigured(getDefaultDbConfig())).toBe(true);
  });

  it("is false when pagila form config lacks host or database", () => {
    const config = getDefaultDbConfig();
    config.connection.host = "";
    expect(isDbConfigured(config)).toBe(false);
    config.connection.host = "localhost";
    config.connection.database = "";
    expect(isDbConfigured(config)).toBe(false);
  });

  it("is true for a non-default datasource_id or DSN mode", () => {
    const custom = getDefaultDbConfig();
    custom.datasource_id = "warehouse";
    custom.connection.host = "";
    expect(isDbConfigured(custom)).toBe(true);

    const dsn = getDefaultDbConfig();
    dsn.connection.mode = "dsn";
    expect(isDbConfigured(dsn)).toBe(true);
  });
});
