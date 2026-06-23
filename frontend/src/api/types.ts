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
  repair_history: RepairHistoryItemPayload[];
  errors: WorkflowErrorPayload[];
  trace: TraceEventPayload[];
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

export interface ApiErrorResponse {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
}
