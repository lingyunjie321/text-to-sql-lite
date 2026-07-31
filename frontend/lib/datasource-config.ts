import type { StoredDbConfig } from "./types";

const STORAGE_KEY = "text-to-sql-db-config";
const CURRENT_VERSION = 1 as const;

export const DEFAULT_PORTS: Record<string, number> = {
  postgresql: 5432,
  mysql: 3306,
  starrocks: 9030,
};

export function getDefaultDbConfig(): StoredDbConfig {
  return {
    version: CURRENT_VERSION,
    datasource_id: "pagila",
    type: "postgresql",
    connection: {
      mode: "form",
      host: "localhost",
      port: 5432,
      database: "pagila",
      username: "postgres",
      password: "",
    },
    auth: {
      schemas: [],
      allowed_tables: [],
    },
    updatedAt: new Date().toISOString(),
  };
}

export function getDbConfig(): StoredDbConfig {
  if (typeof window === "undefined") {
    return getDefaultDbConfig();
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return getDefaultDbConfig();
    const parsed = JSON.parse(raw) as StoredDbConfig;
    if (!parsed || typeof parsed !== "object" || parsed.version !== CURRENT_VERSION) {
      return getDefaultDbConfig();
    }
    const defaults = getDefaultDbConfig();
    return {
      version: CURRENT_VERSION,
      datasource_id: parsed.datasource_id ?? defaults.datasource_id,
      type: parsed.type ?? defaults.type,
      connection: {
        mode: parsed.connection?.mode ?? "form",
        host: parsed.connection?.host ?? "",
        port: parsed.connection?.port ?? DEFAULT_PORTS[parsed.type ?? "postgresql"],
        database: parsed.connection?.database ?? "",
        username: parsed.connection?.username ?? "",
        password: parsed.connection?.password ?? "",
        dsn: parsed.connection?.dsn ?? "",
      },
      auth: {
        schemas: parsed.auth?.schemas ?? [],
        allowed_tables: parsed.auth?.allowed_tables ?? [],
      },
      updatedAt: parsed.updatedAt ?? new Date().toISOString(),
    };
  } catch {
    return getDefaultDbConfig();
  }
}

export function setDbConfig(config: StoredDbConfig): void {
  if (typeof window === "undefined") return;
  const toStore: StoredDbConfig = {
    ...config,
    version: CURRENT_VERSION,
    updatedAt: new Date().toISOString(),
  };
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(toStore));
}

export function clearDbConfig(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(STORAGE_KEY);
}

/**
 * Parse a DSN string like `postgresql://user:pass@host:5432/dbname` into connection fields.
 * Returns null if parsing fails.
 */
export function parseDsn(
  dsn: string,
): {
  type: "postgresql" | "mysql" | "starrocks";
  username: string;
  password: string;
  host: string;
  port: number;
  database: string;
} | null {
  try {
    const match = dsn.match(
      /^(postgresql|mysql|starrocks):\/\/([^:]+):([^@]*)@([^:]+):(\d+)\/(.+)$/,
    );
    if (!match) return null;
    const [, type, username, password, host, portStr, database] = match;
    return {
      type: type as "postgresql" | "mysql" | "starrocks",
      username: decodeURIComponent(username),
      password: decodeURIComponent(password),
      host,
      port: parseInt(portStr, 10),
      database,
    };
  } catch {
    return null;
  }
}

/**
 * Build a DSN string from connection fields.
 */
export function buildDsn(config: {
  type: "postgresql" | "mysql" | "starrocks";
  username: string;
  password: string;
  host: string;
  port: number;
  database: string;
}): string {
  const { type, username, password, host, port, database } = config;
  if (!username || !host || !database) return "";
  return `${type}://${encodeURIComponent(username)}:${encodeURIComponent(password)}@${host}:${port}/${database}`;
}

export function isDbConfigured(config: StoredDbConfig): boolean {
  return config.datasource_id !== "pagila" || config.connection.mode === "dsn"
    ? true
    : !!(config.connection.host && config.connection.database);
}
