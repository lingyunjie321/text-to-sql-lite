export type DialectName = "sqlite" | "postgres" | "mysql";

export type QueryCellValue = string | number | boolean | null;
export type QueryRow = Record<string, QueryCellValue>;

export interface SqlErrorPayload {
  category?: string;
  message: string;
  raw_message?: string | null;
  table?: string | null;
  column?: string | null;
}

export interface SqlExecutionResult {
  success: boolean;
  columns: string[];
  rows: QueryRow[];
  duration_ms: number;
  error?: SqlErrorPayload | null;
}

export interface WorkflowErrorPayload {
  node_name?: string;
  error_type?: string;
  message?: string;
  error?: SqlErrorPayload | string | null;
}

export interface TraceEventPayload {
  node_name: string;
  node_type: string;
  start_time: string;
  end_time: string;
  duration_ms: number;
  status: string;
  outcome: string;
  input_summary: Record<string, unknown>;
  output_summary: Record<string, unknown>;
  error: Record<string, unknown> | null;
}

export interface LinkedColumnPayload {
  name: string;
  type?: string;
  score?: number;
  reasons?: string[];
}

export interface LinkedTablePayload {
  name: string;
  score?: number;
  reasons?: string[];
  columns?: Record<string, LinkedColumnPayload>;
}

export interface LinkedSchemaPayload {
  query?: string;
  tables?: string[] | LinkedTablePayload[];
}

export interface RetrievedExamplePayload {
  natural_language?: string | null;
  sql?: string | null;
  dialect?: string | null;
  involved_tables?: string[];
  score?: number | null;
  reasons?: string[];
}

export interface ReferenceSqlKnowledgePayload {
  name?: string | null;
  natural_language?: string | null;
  sql?: string | null;
  involved_tables?: string[];
}

export interface DocumentKnowledgePayload {
  title?: string | null;
  content?: string | null;
}

export interface MetricKnowledgePayload {
  name?: string | null;
  description?: string | null;
  expression?: string | null;
  involved_tables?: string[];
}

export interface SemanticModelKnowledgePayload {
  name?: string | null;
  description?: string | null;
  tables?: string[];
}

export interface RagContextPayload {
  reference_sql: Array<
    ReferenceSqlKnowledgePayload & { score?: number | null; reasons?: string[] }
  >;
  documents: Array<DocumentKnowledgePayload & { score?: number | null; reasons?: string[] }>;
  metrics: Array<MetricKnowledgePayload & { score?: number | null; reasons?: string[] }>;
  semantic_models: Array<
    SemanticModelKnowledgePayload & { score?: number | null; reasons?: string[] }
  >;
}

export interface RepairHistoryItemPayload {
  attempt?: number;
  old_sql?: string;
  new_sql?: string;
  before_sql?: string;
  after_sql?: string;
  error_type?: string;
  reason?: string;
  explanation?: string;
  error?: {
    message?: string;
  };
}

export interface QueryRunResponse {
  request_id: string;
  status: string;
  final_sql?: string | null;
  result?: SqlExecutionResult | null;
  attempts: number;
  selected_model?: string | null;
  routing_reason?: string | null;
  linked_schema?: LinkedSchemaPayload;
  retrieved_examples: RetrievedExamplePayload[];
  rag_context: RagContextPayload;
  repair_history: RepairHistoryItemPayload[];
  errors: WorkflowErrorPayload[];
  trace: TraceEventPayload[];
}

export interface QueryRunSummaryPayload {
  request_id: string;
  question: string;
  status: string;
  final_sql?: string | null;
  attempts: number;
  selected_model?: string | null;
  routing_reason?: string | null;
  target_dialect: DialectName;
  runtime_config_id?: string | null;
  row_count?: number | null;
  error_message?: string | null;
}

export interface QueryRunListResponse {
  items: QueryRunSummaryPayload[];
  total: number;
}

export interface SavedQueryCreateRequest {
  name: string;
  request_id?: string;
  question?: string;
  sql?: string;
  tags?: string[];
  status?: "draft" | "approved" | "deprecated";
}

export interface SavedQueryResponse {
  id: string;
  name: string;
  question: string;
  sql: string;
  created_from_run_id?: string | null;
  tags: string[];
  status: "draft" | "approved" | "deprecated";
  created_at: string;
  updated_at: string;
}

export interface SavedQueryListResponse {
  items: SavedQueryResponse[];
  total: number;
}

export interface FeedbackCreateRequest {
  rating: "up" | "down" | "neutral";
  issue_type?: string;
  comment?: string;
}

export interface FeedbackResponse {
  id: string;
  request_id: string;
  rating: string;
  issue_type?: string | null;
  comment?: string | null;
  created_at: string;
}

export interface ColumnSchemaPayload {
  type: string;
  nullable?: boolean;
  description?: string | null;
}

export interface TableSchemaPayload {
  name?: string;
  description?: string | null;
  columns: Record<string, ColumnSchemaPayload>;
}

export interface SchemaResponse {
  tables: Record<string, TableSchemaPayload>;
}

export interface RuntimeDatabasePreset {
  id: string;
  driver: "sqlite" | "postgresql" | "mysql";
  display_name: string;
  target_dialect: DialectName;
  read_only: boolean;
}

export interface RuntimeModelPreset {
  id: string;
  provider: string;
  model: string;
  display_name: string;
  requires_secret: boolean;
}

export interface RuntimeOptionsResponse {
  database_presets: RuntimeDatabasePreset[];
  model_presets: {
    light: RuntimeModelPreset[];
    strong: RuntimeModelPreset[];
  };
}

export type RuntimeMode = "preset" | "custom";

export interface RuntimeDatabaseSelection {
  mode: RuntimeMode;
  preset_id?: string;
  config?: {
    driver: "sqlite" | "postgresql" | "mysql";
    sqlite_path?: string;
    host?: string;
    port?: number;
    database_name?: string;
    username?: string;
    password?: string;
    display_name?: string;
    target_dialect?: DialectName;
  };
}

export interface RuntimeModelSelection {
  mode: RuntimeMode;
  preset_id?: string;
  provider?: string;
  model?: string;
  base_url?: string;
  api_key?: string;
  api_key_env?: string;
  temperature?: number;
  max_tokens?: number;
}

export interface RuntimeConfigCreateRequest {
  database: RuntimeDatabaseSelection;
  models: {
    light: RuntimeModelSelection;
    strong: RuntimeModelSelection;
  };
}

export interface RuntimeConfigResponse {
  runtime_config_id: string;
  expires_at: string;
  database: {
    display_name: string;
    driver: string;
    target_dialect: DialectName;
    table_count: number;
    column_count: number;
    tables: string[];
  };
  models: {
    light: { provider: string; model: string };
    strong: { provider: string; model: string };
  };
}

export interface ApiErrorResponse {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
}
