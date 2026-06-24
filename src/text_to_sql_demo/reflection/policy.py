from __future__ import annotations

from hashlib import sha256
from typing import Any

from text_to_sql_demo.reflection.models import (
    ReflectionDecision,
    ReflectionStrategy,
    SQLAttemptContext,
)
from text_to_sql_demo.sql.models import SQLError

_STRATEGY_OUTCOMES = {
    ReflectionStrategy.FIX_SQL: "fix_sql",
    ReflectionStrategy.RELINK_SCHEMA: "relink_schema",
    ReflectionStrategy.RETRIEVE_CONTEXT: "retrieve_context",
    ReflectionStrategy.REASONING_REWRITE: "reasoning_rewrite",
    ReflectionStrategy.HITL: "hitl_required",
    ReflectionStrategy.STOP: "attempts_exhausted",
}

_ERROR_STRATEGIES = {
    "syntax_error": ReflectionStrategy.FIX_SQL,
    "unknown_column": ReflectionStrategy.FIX_SQL,
    "ambiguous_column": ReflectionStrategy.FIX_SQL,
    "unknown_table": ReflectionStrategy.RELINK_SCHEMA,
    "dialect_error": ReflectionStrategy.FIX_SQL,
    "execution_error": ReflectionStrategy.REASONING_REWRITE,
}


def decide_reflection_strategy(
    *,
    error: SQLError,
    attempt_count: int,
    max_attempts: int,
    attempts_exhausted: bool = False,
) -> ReflectionDecision:
    """按错误类别和尝试次数生成反思策略决策。"""
    if attempts_exhausted:
        return ReflectionDecision(
            strategy=ReflectionStrategy.HITL,
            reason="修复尝试次数已达到上限，需要人工确认 SQL、Schema 或业务口径",
            confidence=0.4,
            error_category=error.category,
            attempt_count=attempt_count,
            max_attempts=max_attempts,
            next_hint="请人工检查最近 SQL 尝试、错误类型和 linked schema",
        )

    strategy = _ERROR_STRATEGIES.get(error.category, ReflectionStrategy.HITL)
    return ReflectionDecision(
        strategy=strategy,
        reason=_reason_for_strategy(strategy, error),
        confidence=_confidence_for_strategy(strategy),
        error_category=error.category,
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        next_hint=_next_hint_for_strategy(strategy),
    )


def reflection_outcome(decision: ReflectionDecision) -> str:
    """把反思策略转换成 workflow.yaml 可路由的 outcome。"""
    return _STRATEGY_OUTCOMES[decision.strategy]


def build_sql_attempt_context(
    *,
    state_data: dict[str, Any],
    decision: ReflectionDecision,
    attempt: int,
) -> SQLAttemptContext:
    """从当前状态生成一条轻量 SQL 尝试记忆。"""
    last_error = _normalize_error(state_data.get("last_error"))
    validation_error = _error_from_result(state_data.get("validation_result"))
    execution_error = _error_from_result(state_data.get("execution_result"))
    if validation_error is None and execution_error is None:
        if decision.error_category == "execution_error":
            execution_error = last_error
        else:
            validation_error = last_error

    sql = state_data.get("current_sql") or state_data.get("generated_sql")
    return SQLAttemptContext(
        attempt=attempt,
        sql=str(sql) if sql else None,
        validation_error=validation_error,
        execution_error=execution_error,
        result_summary=_result_summary(state_data.get("execution_result")),
        reflection_strategy=decision.strategy.value,
        reflection_reason=decision.reason,
    )


def build_success_sql_attempt_context(
    *,
    state_data: dict[str, Any],
) -> SQLAttemptContext:
    """为成功执行的最终 SQL 生成一条 workflow memory。"""
    sql = (
        state_data.get("validated_sql")
        or state_data.get("current_sql")
        or state_data.get("generated_sql")
    )
    return SQLAttemptContext(
        attempt=_success_attempt_number(state_data.get("attempt_count")),
        sql=str(sql) if sql else None,
        result_summary=_result_summary(state_data.get("execution_result")),
        reflection_strategy="SUCCESS",
        reflection_reason="SQL 已通过校验并成功执行",
    )


def append_sql_context(
    sql_contexts: object,
    context: SQLAttemptContext,
) -> list[dict[str, Any]]:
    """追加或更新同一轮 SQL 尝试，避免重复记录同一轮失败。"""
    existing_items = [
        item for item in sql_contexts if isinstance(item, dict)
    ] if isinstance(sql_contexts, list) else []
    context_payload = context.model_dump(mode="python")
    for index, item in enumerate(existing_items):
        if item.get("attempt") == context.attempt and item.get("sql") == context.sql:
            existing_items[index] = {**item, **context_payload}
            return existing_items
    return [*existing_items, context_payload]


def append_success_sql_context(
    sql_contexts: object,
    context: SQLAttemptContext,
) -> list[dict[str, Any]]:
    """追加成功 SQL 记忆；同一最终 SQL 已记录 SUCCESS 时只更新摘要。"""
    existing_items = [
        item for item in sql_contexts if isinstance(item, dict)
    ] if isinstance(sql_contexts, list) else []
    context_payload = context.model_dump(mode="python")
    for index, item in enumerate(existing_items):
        if item.get("sql") == context.sql and item.get("reflection_strategy") == "SUCCESS":
            existing_items[index] = {**item, **context_payload}
            return existing_items
    return append_sql_context(existing_items, context)


def format_sql_contexts(sql_contexts: object, limit: int = 3) -> str:
    """把最近 SQLAttemptContext 格式化为 prompt 可读的脱敏摘要。"""
    summarized = summarize_sql_contexts(sql_contexts, limit=limit)
    if not summarized:
        return "无"

    blocks: list[str] = []
    for item in summarized:
        error_category = _context_error_category(item)
        blocks.extend(
            [
                f"- 第 {item['attempt']} 轮",
                f"  - SQL: length={item['sql_length']}, hash={item['sql_hash']}",
                f"  - 错误类型: {error_category or 'unknown'}",
                f"  - 反思策略: {item.get('reflection_strategy') or 'unknown'}",
                f"  - 反思原因: {item.get('reflection_reason') or '未记录'}",
            ]
        )
    return "\n".join(blocks)


def summarize_sql_contexts(
    sql_contexts: object,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """生成 API/Prompt 共用的 SQLContext 脱敏摘要。"""
    if not isinstance(sql_contexts, list):
        return []
    raw_items = [item for item in sql_contexts if isinstance(item, dict)]
    selected_items = raw_items[-limit:] if limit is not None else raw_items
    return [_summarize_sql_context(item) for item in selected_items]


def _summarize_sql_context(item: dict[str, Any]) -> dict[str, Any]:
    sql = item.get("sql")
    sql_text = str(sql) if sql else ""
    return {
        "attempt": int(item.get("attempt", 0)),
        "sql_length": len(sql_text),
        "sql_hash": _hash_sql(sql_text) if sql_text else None,
        "validation_error": _summarize_error(item.get("validation_error")),
        "execution_error": _summarize_error(item.get("execution_error")),
        "result_summary": item.get("result_summary"),
        "reflection_strategy": item.get("reflection_strategy"),
        "reflection_reason": item.get("reflection_reason"),
    }


def _reason_for_strategy(strategy: ReflectionStrategy, error: SQLError) -> str:
    if strategy is ReflectionStrategy.FIX_SQL:
        return f"{error.category} 可通过定向 SQL 修复处理"
    if strategy is ReflectionStrategy.RELINK_SCHEMA:
        return "表引用不存在，先重新执行 Schema Linking 以收窄候选表"
    if strategy is ReflectionStrategy.RETRIEVE_CONTEXT:
        return "上下文不足，重新检索可信业务上下文"
    if strategy is ReflectionStrategy.REASONING_REWRITE:
        return "SQL 执行失败，需要结合错误和上下文重新推理生成"
    if strategy is ReflectionStrategy.HITL:
        return "错误类型无法稳定自动修复，需要人工确认"
    return "达到终止条件，停止自动修复"


def _confidence_for_strategy(strategy: ReflectionStrategy) -> float:
    if strategy in {ReflectionStrategy.FIX_SQL, ReflectionStrategy.RELINK_SCHEMA}:
        return 0.8
    if strategy is ReflectionStrategy.REASONING_REWRITE:
        return 0.7
    if strategy is ReflectionStrategy.RETRIEVE_CONTEXT:
        return 0.65
    return 0.4


def _next_hint_for_strategy(strategy: ReflectionStrategy) -> str | None:
    if strategy is ReflectionStrategy.FIX_SQL:
        return "进入 FixSQLNode，保留用户问题含义并修复当前 SQL"
    if strategy is ReflectionStrategy.RELINK_SCHEMA:
        return "回到 SchemaLinkingNode，重新选择相关表字段后再生成 SQL"
    if strategy is ReflectionStrategy.RETRIEVE_CONTEXT:
        return "回到 ContextRetrievalNode，补充参考 SQL、文档、Metric 或语义模型"
    if strategy is ReflectionStrategy.REASONING_REWRITE:
        return "进入 ReasoningRewriteNode，使用最近反思记忆重新生成 SQL"
    if strategy is ReflectionStrategy.HITL:
        return "进入 HITLNode，标记人工介入"
    return None


def _success_attempt_number(attempt_count: object) -> int:
    if isinstance(attempt_count, int | float | str):
        try:
            return max(1, int(attempt_count) + 1)
        except ValueError:
            return 1
    return 1


def _error_from_result(result: object) -> dict[str, Any] | None:
    if not isinstance(result, dict) or result.get("success") is not False:
        return None
    return _normalize_error(result.get("error"))


def _normalize_error(error: object) -> dict[str, Any] | None:
    if isinstance(error, dict):
        return {
            key: value
            for key, value in error.items()
            if key in {"category", "message", "raw_message", "table", "column"}
        }
    return None


def _result_summary(result: object) -> dict[str, Any] | None:
    if not isinstance(result, dict) or result.get("success") is not True:
        return None
    rows = result.get("rows")
    columns = result.get("columns")
    return {
        "row_count": len(rows) if isinstance(rows, list) else 0,
        "column_count": len(columns) if isinstance(columns, list) else 0,
        "duration_ms": result.get("duration_ms", 0),
    }


def _summarize_error(error: object) -> dict[str, Any] | None:
    normalized = _normalize_error(error)
    if normalized is None:
        return None
    return {
        "category": normalized.get("category"),
        "message": normalized.get("message"),
    }


def _context_error_category(item: dict[str, Any]) -> str | None:
    for key in ("validation_error", "execution_error"):
        error = item.get(key)
        if isinstance(error, dict) and isinstance(error.get("category"), str):
            return error["category"]
    return None


def _hash_sql(sql: str) -> str:
    return f"sha256:{sha256(sql.encode('utf-8')).hexdigest()[:16]}"
