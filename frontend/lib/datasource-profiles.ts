import { ProfileApiError } from "./model-profiles";

export type DatabaseType = "postgresql" | "mysql";

export interface DatasourceProfileResponse {
  id: string;
  name: string;
  database_type: DatabaseType;
  host: string;
  port: number;
  database: string;
  username: string;
  allowed_schemas: string[];
  allowed_tables: string[];
  password_status: "configured" | "missing";
}

export interface DatasourceProfileWriteRequest {
  id: string;
  name: string;
  database_type: DatabaseType;
  host: string;
  port: number;
  database: string;
  username: string;
  allowed_schemas: string[];
  allowed_tables: string[];
  password?: string | null;
}

export interface DatasourceProfileFormValue {
  id: string;
  name: string;
  databaseType: DatabaseType;
  host: string;
  port: string | number;
  database: string;
  username: string;
  password: string;
  clearPassword: boolean;
  allowedTables: string[];
}

export interface DatasourceConnectionTestRequest {
  database_type: DatabaseType;
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
}

export interface MetadataLimits {
  timeout_seconds: number;
  max_relations: number;
  max_columns: number;
  max_foreign_keys: number;
}

export interface RelationSummary {
  schema: string;
  name: string;
  kind: "table" | "view";
}

export interface DatasourceConnectionTestResponse {
  status: "ok";
  schemas: string[];
  relations: RelationSummary[];
  truncated: boolean;
  limits: MetadataLimits;
}

export interface MetadataColumn {
  name: string;
  data_type: string;
  nullable: boolean;
}

export interface MetadataRelation {
  name: string;
  kind: "table" | "view";
  columns: MetadataColumn[];
  primary_key: string[];
}

export interface MetadataSchema {
  name: string;
  relations: MetadataRelation[];
}

export interface DatasourceMetadataResponse {
  datasource_id: string;
  schemas: MetadataSchema[];
  foreign_keys: MetadataForeignKey[];
  truncated: boolean;
  limits: MetadataLimits;
}

export interface MetadataForeignKey {
  name: string;
  source_schema: string;
  source_table: string;
  source_columns: string[];
  target_schema: string;
  target_table: string;
  target_columns: string[];
}

type JsonParser<T> = (value: unknown) => T;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString);
}

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

function invalidResponseError(): ProfileApiError {
  return new ProfileApiError(
    "Received an invalid datasource profile response.",
    "PROFILE_API_INVALID_RESPONSE",
  );
}

function parseLimits(value: unknown): MetadataLimits {
  if (
    !isRecord(value) ||
    typeof value.timeout_seconds !== "number" ||
    !isInteger(value.max_relations) ||
    !isInteger(value.max_columns) ||
    !isInteger(value.max_foreign_keys)
  ) {
    throw invalidResponseError();
  }
  return {
    timeout_seconds: value.timeout_seconds,
    max_relations: value.max_relations,
    max_columns: value.max_columns,
    max_foreign_keys: value.max_foreign_keys,
  };
}

export function parseDatasourceProfileResponse(
  value: unknown,
): DatasourceProfileResponse {
  if (!isRecord(value)) throw invalidResponseError();
  const databaseType = value.database_type;
  const passwordStatus = value.password_status;
  if (
    !isString(value.id) ||
    !isString(value.name) ||
    (databaseType !== "postgresql" && databaseType !== "mysql") ||
    !isString(value.host) ||
    !isInteger(value.port) ||
    !isString(value.database) ||
    !isString(value.username) ||
    !isStringArray(value.allowed_schemas) ||
    !isStringArray(value.allowed_tables) ||
    (passwordStatus !== "configured" && passwordStatus !== "missing")
  ) {
    throw invalidResponseError();
  }
  return {
    id: value.id,
    name: value.name,
    database_type: databaseType,
    host: value.host,
    port: value.port,
    database: value.database,
    username: value.username,
    allowed_schemas: value.allowed_schemas,
    allowed_tables: value.allowed_tables,
    password_status: passwordStatus,
  };
}

function parseMetadataColumn(value: unknown): MetadataColumn {
  if (
    !isRecord(value) ||
    !isString(value.name) ||
    !isString(value.data_type) ||
    typeof value.nullable !== "boolean"
  ) {
    throw invalidResponseError();
  }
  return { name: value.name, data_type: value.data_type, nullable: value.nullable };
}

function parseMetadataRelation(value: unknown): MetadataRelation {
  if (
    !isRecord(value) ||
    !isString(value.name) ||
    (value.kind !== "table" && value.kind !== "view") ||
    !Array.isArray(value.columns) ||
    !isStringArray(value.primary_key)
  ) {
    throw invalidResponseError();
  }
  return {
    name: value.name,
    kind: value.kind,
    columns: value.columns.map(parseMetadataColumn),
    primary_key: value.primary_key,
  };
}

function parseMetadataSchema(value: unknown): MetadataSchema {
  if (!isRecord(value) || !isString(value.name) || !Array.isArray(value.relations)) {
    throw invalidResponseError();
  }
  return { name: value.name, relations: value.relations.map(parseMetadataRelation) };
}

const FOREIGN_KEY_FIELDS = new Set([
  "name",
  "source_schema",
  "source_table",
  "source_columns",
  "target_schema",
  "target_table",
  "target_columns",
]);

function parseMetadataForeignKey(value: unknown): MetadataForeignKey {
  if (
    !isRecord(value) ||
    Object.keys(value).length !== FOREIGN_KEY_FIELDS.size ||
    Object.keys(value).some((key) => !FOREIGN_KEY_FIELDS.has(key)) ||
    !isString(value.name) ||
    !isString(value.source_schema) ||
    !isString(value.source_table) ||
    !isStringArray(value.source_columns) ||
    !isString(value.target_schema) ||
    !isString(value.target_table) ||
    !isStringArray(value.target_columns)
  ) {
    throw invalidResponseError();
  }
  return {
    name: value.name,
    source_schema: value.source_schema,
    source_table: value.source_table,
    source_columns: value.source_columns,
    target_schema: value.target_schema,
    target_table: value.target_table,
    target_columns: value.target_columns,
  };
}

export function parseDatasourceMetadataResponse(
  value: unknown,
): DatasourceMetadataResponse {
  if (
    !isRecord(value) ||
    !isString(value.datasource_id) ||
    !Array.isArray(value.schemas) ||
    !Array.isArray(value.foreign_keys) ||
    typeof value.truncated !== "boolean"
  ) {
    throw invalidResponseError();
  }
  return {
    datasource_id: value.datasource_id,
    schemas: value.schemas.map(parseMetadataSchema),
    foreign_keys: value.foreign_keys.map(parseMetadataForeignKey),
    truncated: value.truncated,
    limits: parseLimits(value.limits),
  };
}

function parseConnectionTestResponse(value: unknown): DatasourceConnectionTestResponse {
  if (
    !isRecord(value) ||
    value.status !== "ok" ||
    !isStringArray(value.schemas) ||
    !Array.isArray(value.relations) ||
    typeof value.truncated !== "boolean"
  ) {
    throw invalidResponseError();
  }
  const relations: RelationSummary[] = value.relations.map((relation) => {
    if (
      !isRecord(relation) ||
      !isString(relation.schema) ||
      !isString(relation.name) ||
      (relation.kind !== "table" && relation.kind !== "view")
    ) {
      throw invalidResponseError();
    }
    return {
      schema: relation.schema,
      name: relation.name,
      kind: relation.kind as "table" | "view",
    };
  });
  return {
    status: "ok",
    schemas: value.schemas,
    relations,
    truncated: value.truncated,
    limits: parseLimits(value.limits),
  };
}

export function buildDatasourceWriteRequest(
  value: DatasourceProfileFormValue,
  options: { mode: "create" | "edit" },
): DatasourceProfileWriteRequest {
  const allowedSchemas = [...new Set(
    value.allowedTables.map((table) => table.split(".", 1)[0]).filter(Boolean),
  )];
  const request: DatasourceProfileWriteRequest = {
    id: value.id,
    name: value.name,
    database_type: value.databaseType,
    host: value.host,
    port: Number(value.port),
    database: value.database,
    username: value.username,
    allowed_schemas: allowedSchemas,
    allowed_tables: [...value.allowedTables],
  };
  if (value.clearPassword) request.password = null;
  else if (value.password.trim()) request.password = value.password;
  else if (options.mode === "create") request.password = value.password;
  return request;
}

async function readJson(response: Response): Promise<unknown | undefined> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

function apiError(value: unknown, status: number): ProfileApiError {
  if (
    isRecord(value) &&
    isRecord(value.detail) &&
    isString(value.detail.code) &&
    isString(value.detail.message)
  ) {
    return new ProfileApiError(value.detail.message, value.detail.code);
  }
  return new ProfileApiError(
    status === 422 ? "数据源配置校验失败，请检查填写内容。" : undefined,
  );
}

async function request<T>(path: string, init: RequestInit, parse: JsonParser<T>): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ProfileApiError("Unable to complete datasource profile request.");
  }
  const body = await readJson(response);
  if (!response.ok) throw apiError(body, response.status);
  if (body === undefined) throw invalidResponseError();
  return parse(body);
}

function json(method: "POST" | "PUT", body: object): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const listDatasourceProfiles = () =>
  request("/api/v1/local/datasources", { method: "GET" }, (value) => {
    if (!Array.isArray(value)) throw invalidResponseError();
    return value.map(parseDatasourceProfileResponse);
  });

export const testDatasourceConnection = (body: DatasourceConnectionTestRequest) =>
  request(
    "/api/v1/local/datasources/test",
    json("POST", body),
    parseConnectionTestResponse,
  );

export const createDatasourceProfile = (body: DatasourceProfileWriteRequest) =>
  request(
    "/api/v1/local/datasources",
    json("POST", body),
    parseDatasourceProfileResponse,
  );

export const replaceDatasourceProfile = (
  id: string,
  body: DatasourceProfileWriteRequest,
) =>
  request(
    `/api/v1/local/datasources/${encodeURIComponent(id)}`,
    json("PUT", body),
    parseDatasourceProfileResponse,
  );

export const getDatasourceMetadata = (id: string) =>
  request(
    `/api/v1/local/datasources/${encodeURIComponent(id)}/metadata`,
    { method: "GET" },
    parseDatasourceMetadataResponse,
  );

export async function deleteDatasourceProfile(id: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api/v1/local/datasources/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  } catch {
    throw new ProfileApiError("Unable to complete datasource profile request.");
  }
  if (response.status === 204) return;
  throw apiError(await readJson(response), response.status);
}
