// TypeScript types aligned with backend app/api/models.py

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export type FinalStatus =
  | "SUCCEEDED_FIRST_PASS"
  | "SUCCEEDED_REPAIRED"
  | "CLARIFICATION_REQUIRED"
  | "REJECTED_SECURITY"
  | "FAILED_DUPLICATE_LOOP"
  | "FAILED_TIMEOUT"
  | "FAILED_CONNECTION"
  | "FAILED_RESOURCE_RISK"
  | "FAILED_REPAIR_EXHAUSTED"
  | "FAILED_INTERNAL";

export type ErrorType =
  | "SYNTAX_ERROR"
  | "SCHEMA_ERROR"
  | "DIALECT_ERROR"
  | "BUSINESS_KNOWLEDGE_MISSING"
  | "AMBIGUOUS_SEMANTICS"
  | "PERMISSION_DENIED"
  | "CONNECTION_ERROR"
  | "TIMEOUT"
  | "RESOURCE_RISK"
  | "DUPLICATE_SQL"
  | "UNKNOWN";

// ========================
// Query Request
// ========================

// ========================
// Model / Datasource Override types (Phase 2)
// ========================

export interface ModelEndpointOverride {
  base_url: string;
  api_key: string;
  model_name: string;
}

export interface DatasourceOverride {
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  type: string;
  schemas: string[];
  allowed_tables: string[];
}

export interface QueryRequest {
  question: string;
  datasource_id?: string;
  schemas?: string[];
  debug?: boolean;
  // --- 前端配置传递（仅传覆写值，不传 enabled 等前端专用字段）---
  model_overrides?: Record<string, ModelEndpointOverride>;
  datasource_override?: DatasourceOverride;
}

export interface ResponseColumn {
  name: string;
  type_oid: number;
}

export interface ResponseClarification {
  code: string;
  question: string;
}

export interface PublicError {
  error_type: ErrorType;
  code: string;
  message: string;
}

// ========================
// 新增：查询结果增强类型（⚠️ 需要后端扩展，全部可选）
// ========================

/**
 * Schema Linking 候选表
 * ⚠️ 需要后端扩展：在 QueryResponse 中新增 schema_candidates 字段
 */
export interface SchemaCandidate {
  table_name: string;
  schema: string;
  fields: string[];
  score: number;
  source: "bm25" | "embedding" | "rerank";
  selected: boolean;
}

/**
 * 业务知识 RAG 命中片段
 * ⚠️ 需要后端扩展：在 QueryResponse 中新增 semantic_references 字段
 */
export interface SemanticReference {
  type: "caliber" | "metric" | "glossary" | "few_shot";
  title: string;
  content: string;
  score: number;
}

/**
 * 复杂度路由结果
 * ⚠️ 需要后端扩展：在 QueryResponse 中新增 complexity_route 字段
 */
export interface ComplexityRoute {
  level: "simple" | "standard" | "complex";
  top_k: number;
  model_used: string;
  reason: string;
}

/**
 * 修复过程详情
 * ⚠️ 需要后端扩展：在 QueryResponse 中新增 repair_history 字段
 */
export interface RepairHistoryEntry {
  attempt: number;
  error_type: string;
  fix_strategy: string;
  fingerprint: string;
}

// ========================
// 新增：请求体配置类型（用于设置页面配置传递）
// ========================

export interface ModelEndpoint {
  base_url: string;
  api_key: string;
  model_name: string;
  enabled: boolean;
}

export interface RequestModelConfig {
  simple?: ModelEndpoint;
  standard?: ModelEndpoint;
  complex?: ModelEndpoint;
  fallback?: ModelEndpoint;
}

export interface RequestDatasourceConfig {
  datasource_id: string;
  type: "postgresql" | "mysql" | "starrocks";
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  schemas: string[];
  allowed_tables: string[];
}

// ========================
// 新增：localStorage 存储类型
// ========================

export type ModelTier = "simple" | "standard" | "complex" | "fallback";

export interface StoredModelConfig {
  version: 1;
  models: {
    simple: ModelEndpoint;
    standard: ModelEndpoint;
    complex: ModelEndpoint;
    fallback: ModelEndpoint;
  };
  updatedAt: string;
}

export interface StoredDbConfig {
  version: 1;
  datasource_id: string;
  type: "postgresql" | "mysql" | "starrocks";
  connection: {
    mode: "form" | "dsn";
    host?: string;
    port?: number;
    database?: string;
    username?: string;
    password?: string;
    dsn?: string;
  };
  auth: {
    schemas: string[];
    allowed_tables: string[];
  };
  updatedAt: string;
}

// ========================
// Query Response
// ========================

export interface QueryResponse {
  request_id: string;
  trace_id: string;
  status: FinalStatus;
  sql?: string | null;
  columns?: ResponseColumn[];
  rows?: JsonValue[][];
  returned_row_count?: number;
  truncated?: boolean;
  attempts?: number;
  repair_count?: number;
  clarification?: ResponseClarification | null;
  error?: PublicError | null;

  // --- 新增字段（⚠️ 需要后端扩展，全部可选）---
  schema_candidates?: SchemaCandidate[];
  semantic_references?: SemanticReference[];
  complexity_route?: ComplexityRoute;
  repair_history?: RepairHistoryEntry[];
}

// Helper type guards
export function isSuccess(
  res: QueryResponse,
): res is QueryResponse & {
  status: "SUCCEEDED_FIRST_PASS" | "SUCCEEDED_REPAIRED";
  sql: string;
  columns: ResponseColumn[];
  rows: JsonValue[][];
  returned_row_count: number;
  truncated: boolean;
  attempts: number;
  repair_count: number;
} {
  return (
    res.status === "SUCCEEDED_FIRST_PASS" ||
    res.status === "SUCCEEDED_REPAIRED"
  );
}

export function isClarification(
  res: QueryResponse,
): res is QueryResponse & {
  status: "CLARIFICATION_REQUIRED";
  clarification: ResponseClarification;
} {
  return res.status === "CLARIFICATION_REQUIRED";
}

export function isError(
  res: QueryResponse,
): res is QueryResponse & {
  status:
    | "REJECTED_SECURITY"
    | "FAILED_DUPLICATE_LOOP"
    | "FAILED_TIMEOUT"
    | "FAILED_CONNECTION"
    | "FAILED_RESOURCE_RISK"
    | "FAILED_REPAIR_EXHAUSTED"
    | "FAILED_INTERNAL";
  error: PublicError;
} {
  return (
    res.status !== "SUCCEEDED_FIRST_PASS" &&
    res.status !== "SUCCEEDED_REPAIRED" &&
    res.status !== "CLARIFICATION_REQUIRED"
  );
}
