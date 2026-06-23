from __future__ import annotations

import logging
from typing import Any

from text_to_sql_demo.observability.logging import get_logger
from text_to_sql_demo.observability.redaction import summarize_sql

_logger = get_logger("observability")


def log_api_request_started(*, method: str, path: str, request_id: str) -> None:
    _log(
        logging.INFO,
        "api.request.started",
        method=method,
        path=path,
        request_id=request_id,
    )


def log_api_request_completed(
    *,
    method: str,
    path: str,
    request_id: str,
    status_code: int,
    duration_ms: int,
) -> None:
    _log(
        logging.INFO,
        "api.request.completed",
        method=method,
        path=path,
        request_id=request_id,
        status_code=status_code,
        duration_ms=duration_ms,
    )


def log_api_request_failed(
    *,
    method: str,
    path: str,
    request_id: str,
    duration_ms: int,
    error: BaseException,
) -> None:
    _log(
        logging.ERROR,
        "api.request.failed",
        method=method,
        path=path,
        request_id=request_id,
        duration_ms=duration_ms,
        error=error,
    )


def log_service_initialization_started() -> None:
    _log(logging.INFO, "service.initialization.started")


def log_service_initialization_completed() -> None:
    _log(logging.INFO, "service.initialization.completed")


def log_service_initialization_failed(*, error: BaseException) -> None:
    _log(logging.ERROR, "service.initialization.failed", error=error)


def log_database_url_resolved(*, connection_name: str, database_driver: str) -> None:
    _log(
        logging.INFO,
        "database.url.resolved",
        connection_name=connection_name,
        database_driver=database_driver,
    )


def log_database_url_resolve_failed(
    *,
    connection_name: str,
    database_driver: str | None,
    error: BaseException,
) -> None:
    _log(
        logging.ERROR,
        "database.url.resolve_failed",
        connection_name=connection_name,
        database_driver=database_driver,
        error=error,
    )


def log_llm_client_configured(*, provider: str, alias_count: int) -> None:
    _log(
        logging.INFO,
        "llm.client.configured",
        provider=provider,
        alias_count=alias_count,
    )


def log_llm_client_configure_failed(
    *,
    provider: str,
    api_key_env: str | None = None,
    error: BaseException,
) -> None:
    _log(
        logging.ERROR,
        "llm.client.configure_failed",
        provider=provider,
        api_key_env=api_key_env,
        error=error,
    )


def log_llm_request_completed(
    *,
    provider: str,
    model_alias: str,
    model_name: str,
    duration_ms: int,
    usage: dict[str, int] | None = None,
) -> None:
    _log(
        logging.INFO,
        "llm.request.completed",
        provider=provider,
        model_alias=model_alias,
        model_name=model_name,
        duration_ms=duration_ms,
        usage=usage,
    )


def log_llm_request_failed(
    *,
    provider: str,
    model_alias: str,
    model_name: str,
    duration_ms: int,
    error: BaseException,
) -> None:
    _log(
        logging.ERROR,
        "llm.request.failed",
        provider=provider,
        model_alias=model_alias,
        model_name=model_name,
        duration_ms=duration_ms,
        error=error,
    )


def log_workflow_started(*, request_id: str, workflow_name: str) -> None:
    _log(
        logging.INFO,
        "workflow.started",
        request_id=request_id,
        workflow_name=workflow_name,
    )


def log_workflow_completed(
    *,
    request_id: str,
    workflow_name: str,
    termination_reason: str | None,
    duration_ms: int,
) -> None:
    _log(
        logging.INFO,
        "workflow.completed",
        request_id=request_id,
        workflow_name=workflow_name,
        termination_reason=termination_reason,
        duration_ms=duration_ms,
    )


def log_workflow_failed(
    *,
    request_id: str,
    workflow_name: str,
    termination_reason: str | None,
    duration_ms: int,
) -> None:
    _log(
        logging.ERROR,
        "workflow.failed",
        request_id=request_id,
        workflow_name=workflow_name,
        termination_reason=termination_reason,
        duration_ms=duration_ms,
    )


def log_node_started(
    *,
    request_id: str,
    workflow_name: str,
    node_name: str,
    node_type: str,
    step: int,
) -> None:
    _log(
        logging.INFO,
        "workflow.node.started",
        request_id=request_id,
        workflow_name=workflow_name,
        node_name=node_name,
        node_type=node_type,
        step=step,
    )


def log_node_completed(
    *,
    request_id: str,
    workflow_name: str,
    node_name: str,
    node_type: str,
    outcome: str,
    duration_ms: int,
    step: int,
) -> None:
    _log(
        logging.INFO,
        "workflow.node.completed",
        request_id=request_id,
        workflow_name=workflow_name,
        node_name=node_name,
        node_type=node_type,
        outcome=outcome,
        duration_ms=duration_ms,
        step=step,
    )


def log_node_failed(
    *,
    request_id: str,
    workflow_name: str,
    node_name: str,
    node_type: str,
    outcome: str,
    duration_ms: int,
    step: int,
    error: BaseException,
) -> None:
    _log(
        logging.ERROR,
        "workflow.node.failed",
        request_id=request_id,
        workflow_name=workflow_name,
        node_name=node_name,
        node_type=node_type,
        outcome=outcome,
        duration_ms=duration_ms,
        step=step,
        error=error,
    )


def log_sql_validation_failed(
    *,
    request_id: str,
    node_name: str,
    error_category: str | None,
    sql: str,
) -> None:
    _log(
        logging.WARNING,
        "sql.validation.failed",
        request_id=request_id,
        node_name=node_name,
        sql_error_category=error_category,
        **summarize_sql(sql),
    )


def log_sql_execution_failed(
    *,
    request_id: str,
    node_name: str,
    error_category: str | None,
    sql: str,
) -> None:
    _log(
        logging.WARNING,
        "sql.execution.failed",
        request_id=request_id,
        node_name=node_name,
        sql_error_category=error_category,
        **summarize_sql(sql),
    )


def log_repair_attempted(
    *,
    request_id: str,
    node_name: str,
    attempt_count: int,
    max_attempts: int,
    error_category: str,
) -> None:
    _log(
        logging.WARNING,
        "repair.attempted",
        request_id=request_id,
        node_name=node_name,
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        sql_error_category=error_category,
    )


def log_repair_exhausted(
    *,
    request_id: str,
    node_name: str,
    attempt_count: int,
    max_attempts: int,
    error_category: str,
) -> None:
    _log(
        logging.WARNING,
        "repair.exhausted",
        request_id=request_id,
        node_name=node_name,
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        sql_error_category=error_category,
    )


def _log(level: int, event: str, *, error: BaseException | None = None, **fields: Any) -> None:
    extra = {"event": event, **fields}
    if error is None:
        _logger.log(level, event, extra=extra, stacklevel=3)
        return
    _logger.log(
        level,
        event,
        extra=extra,
        exc_info=(type(error), error, error.__traceback__),
        stacklevel=3,
    )
