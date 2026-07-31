from __future__ import annotations

from app.api.models import (
    ComplexityRoute,
    PublicError,
    QueryResponse,
    RepairHistoryEntry,
    ResponseClarification,
    ResponseColumn,
    SchemaCandidate,
)
from app.connectors.models import ExecutionResult
from app.reflection import SQLAttempt
from app.schema_linking import CandidateTable
from app.workflow import (
    FinalStatus,
    SQLTaskState,
)


def build_query_response(state: SQLTaskState) -> QueryResponse:
    if state.final_status is None:
        raise ValueError("workflow state is not terminal")
    base: dict[str, object] = {
        "request_id": state.request_id,
        "trace_id": state.trace_id,
        "status": state.final_status,
        "attempts": len(state.sql_attempts),
        "repair_count": state.repair_count,
    }
    if state.final_status in {
        FinalStatus.SUCCEEDED_FIRST_PASS,
        FinalStatus.SUCCEEDED_REPAIRED,
    }:
        result = state.execution_result
        if not isinstance(result, ExecutionResult):
            raise ValueError("workflow success result is invalid")
        base.update(
            {
                "sql": state.current_sql,
                "columns": tuple(
                    ResponseColumn(
                        name=column.name,
                        type_oid=column.type_oid,
                    )
                    for column in result.columns
                ),
                "rows": [list(row) for row in result.rows],
                "returned_row_count": result.returned_row_count,
                "truncated": result.truncated,
            }
        )
    elif (
        state.final_status
        == FinalStatus.CLARIFICATION_REQUIRED
    ):
        if state.clarification is None:
            raise ValueError("workflow clarification is invalid")
        base["clarification"] = ResponseClarification(
            code=state.clarification.code,
            question=state.clarification.question,
        )
    else:
        if state.public_error is None:
            raise ValueError("workflow public error is invalid")
        base["error"] = PublicError(
            error_type=state.public_error.error_type,
            code=state.public_error.code,
            message=state.public_error.public_message,
        )

    # ── Phase 3: 映射扩展字段 ──────────────────────────────────────────

    _map_schema_candidates(state, base)
    _map_complexity_route(state, base)
    _map_repair_history(state, base)

    return QueryResponse.model_validate(base)


def _map_schema_candidates(
    state: SQLTaskState,
    base: dict[str, object],
) -> None:
    """从 candidate_tables / candidate_fields 构建 schema_candidates。"""
    if not state.candidate_tables:
        return

    # 确定哪些表名有被选中的字段
    selected_table_names: set[str] = set()
    for field_id in state.selected_generation_field_ids:
        for cf in state.candidate_fields:
            if cf.object_id == field_id:
                selected_table_names.add(cf.table_name)
                break

    tables = [
        t
        for t in state.candidate_tables
        if isinstance(t, CandidateTable)
    ]
    candidates: list[dict[str, object]] = []
    for t in tables:
        fields = [
            f.column_name
            for f in state.candidate_fields
            if f.schema_name == t.schema_name
            and f.table_name == t.table_name
        ]
        candidates.append(
            {
                "table_name": t.table_name,
                "schema": t.schema_name,
                "fields": fields,
                "score": t.score,
                "source": getattr(t, "source", "bm25"),
                "selected": t.table_name in selected_table_names,
            }
        )
    if candidates:
        base["schema_candidates"] = candidates


def _map_complexity_route(
    state: SQLTaskState,
    base: dict[str, object],
) -> None:
    """从 complexity_decision 构建 complexity_route。"""
    if state.complexity_decision is None:
        return

    d = state.complexity_decision
    model_used = "unknown"
    if state.model_routing_observations:
        last_route = state.model_routing_observations[-1]
        model_used = last_route.route_id

    base["complexity_route"] = {
        "level": (
            d.level.value
            if hasattr(d.level, "value")
            else str(d.level)
        ),
        "top_k": d.schema_top_k,
        "model_used": model_used,
        "reason": (
            ", ".join(r.value for r in d.reason_codes)
            if d.reason_codes
            else "default"
        ),
    }


def _map_repair_history(
    state: SQLTaskState,
    base: dict[str, object],
) -> None:
    """从 sql_attempts 构建 repair_history（跳过首次成功尝试）。"""
    if state.repair_count <= 0:
        return

    repair_entries: list[dict[str, object]] = []
    for i, attempt in enumerate(state.sql_attempts):
        if not isinstance(attempt, SQLAttempt):
            continue
        if i == 0:
            # 跳过首次尝试（非修复）
            continue
        error_type = "UNKNOWN"
        if attempt.validation_result is not None:
            issue = attempt.validation_result.issue
            if issue is not None:
                error_type = str(issue.error_type)
        elif attempt.database_error is not None:
            error_type = str(attempt.database_error.error_type)

        repair_entries.append(
            {
                "attempt": i,
                "error_type": error_type,
                "fix_strategy": (
                    str(state.repair_strategy)
                    if state.repair_strategy is not None
                    else "N/A"
                ),
                "fingerprint": attempt.fingerprint,
            }
        )

    if repair_entries:
        base["repair_history"] = repair_entries
