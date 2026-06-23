import type {
  DialectName,
  LinkedSchemaPayload,
  QueryCellValue,
  QueryRunResponse,
  RetrievedExamplePayload,
  TraceEventPayload,
  WorkflowErrorPayload
} from "../api/types";

export type SqlViewStatus = "generated_valid" | "repaired_valid" | "failed";

export interface QueryResultView {
  columns: string[];
  rows: Record<string, QueryCellValue>[];
  rowCount: number;
  executionMs: number;
}

export interface RepairNoticeView {
  summary: string;
  error: string;
  explanation: string;
  beforeSql: string;
  afterSql: string;
}

export interface GenerationDetailsView {
  usedTables: string[];
  validationResult: "通过" | "未通过";
  repairCount: number;
  databaseType: DialectName;
  executionMs: number | null;
  rowCount: number | null;
}

export interface DeveloperInfoView {
  model: string | null;
  routingReason: string | null;
  retrievedExamples: RetrievedExamplePayload[];
  trace: TraceEventPayload[];
  errors: WorkflowErrorPayload[];
}

export interface UserErrorView {
  message: string;
}

export interface QueryRunView {
  requestId: string;
  sqlStatus: SqlViewStatus;
  statusText: string;
  sql: string;
  result: QueryResultView | null;
  repairNotice: RepairNoticeView | null;
  details: GenerationDetailsView;
  developerInfo: DeveloperInfoView;
  userError: UserErrorView | null;
}

export function adaptQueryRun(
  response: QueryRunResponse,
  databaseType: DialectName
): QueryRunView {
  const success = response.status === "success" && response.result?.success === true;
  const repairCount = response.attempts;
  const sqlStatus: SqlViewStatus = success
    ? repairCount > 0
      ? "repaired_valid"
      : "generated_valid"
    : "failed";
  const result = success && response.result ? adaptResult(response.result) : null;
  const userError = success ? null : { message: firstUserError(response) };

  return {
    requestId: response.request_id,
    sqlStatus,
    statusText: statusText(sqlStatus),
    sql: response.final_sql ?? "",
    result,
    repairNotice: success && repairCount > 0 ? adaptRepairNotice(response) : null,
    details: {
      usedTables: usedTables(response.linked_schema),
      validationResult: success ? "通过" : "未通过",
      repairCount,
      databaseType,
      executionMs: result?.executionMs ?? null,
      rowCount: result?.rowCount ?? null
    },
    developerInfo: {
      model: response.selected_model ?? null,
      routingReason: response.routing_reason ?? null,
      retrievedExamples: response.retrieved_examples,
      trace: response.trace,
      errors: response.errors
    },
    userError
  };
}

function adaptResult(result: NonNullable<QueryRunResponse["result"]>): QueryResultView {
  return {
    columns: result.columns,
    rows: result.rows,
    rowCount: result.rows.length,
    executionMs: result.duration_ms
  };
}

function adaptRepairNotice(response: QueryRunResponse): RepairNoticeView {
  const latest = response.repair_history.at(-1);
  const repairCount = Math.max(response.attempts, response.repair_history.length);
  const errorText = [latest?.error_type, latest?.error?.message, latest?.reason]
    .filter(Boolean)
    .join(" ");
  const issueType =
    errorText.includes("unknown_column") || errorText.includes("字段") ? "字段引用问题" : "SQL 问题";

  return {
    summary: `系统已自动修复 ${repairCount} 处${issueType}`,
    error: latest?.error?.message ?? latest?.reason ?? latest?.error_type ?? "SQL 校验未通过",
    explanation: latest?.explanation ?? latest?.reason ?? "已根据校验结果调整 SQL。",
    beforeSql: latest?.before_sql ?? latest?.old_sql ?? "",
    afterSql: latest?.after_sql ?? latest?.new_sql ?? response.final_sql ?? ""
  };
}

function statusText(status: SqlViewStatus): string {
  if (status === "generated_valid") {
    return "SQL 已生成并通过验证";
  }
  if (status === "repaired_valid") {
    return "SQL 已修复并通过验证";
  }
  return "未能生成可执行 SQL";
}

function usedTables(linkedSchema: LinkedSchemaPayload | undefined): string[] {
  const tables = linkedSchema?.tables;
  if (!tables) {
    return [];
  }
  return tables
    .map((table) => (typeof table === "string" ? table : table.name))
    .filter((tableName) => tableName.length > 0);
}

function firstUserError(response: QueryRunResponse): string {
  const executionError = response.result?.error?.message;
  if (executionError) {
    return executionError;
  }

  for (const error of response.errors) {
    if (error.message) {
      return error.message;
    }
    if (typeof error.error === "string") {
      return error.error;
    }
    if (error.error?.message) {
      return error.error.message;
    }
  }

  return "生成结果未通过验证，请调整问题后重试。";
}
