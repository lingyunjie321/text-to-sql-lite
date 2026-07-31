"""Schema Linking 节点：在授权范围内检索候选表/字段/FK 路径（探测与物化两次）。"""

from __future__ import annotations

from app.connectors.errors import PostgreSQLConnectorError
from app.schema_linking import (
    PROBE_SCHEMA_TOP_K,
    EmbeddingIndexBuildError,
    EmbeddingProviderError,
    SchemaRetrievalFailure,
    link_schema,
)
from app.workflow.models import SQLTaskState, WorkflowContext
from app.workflow.nodes._common import (
    NodeUpdate,
    _INTERNAL_ERROR,
    _NO_SCHEMA_ERROR,
    _EMBEDDING_PUBLIC_ERRORS,
    _consume_infrastructure_retries,
    _failure_update,
    _public_database_error,
    _public_embedding_error,
)
from app.reflection import RepairStrategy


def _schema_linking(
    state: SQLTaskState,
    context: WorkflowContext,
    *,
    deadline_at: float,
    database_timeout_seconds: float,
) -> NodeUpdate:
    assert state.normalized_question is not None
    decision = state.complexity_decision
    if decision is None:
        try:
            snapshot = context.connector.read_metadata(
                state.allowed_schemas,
                state.allowed_tables,
                timeout_seconds=database_timeout_seconds,
            )
        except PostgreSQLConnectorError as error:
            update = _failure_update(_public_database_error(error))
            update["infrastructure_retry_count"] = (
                state.infrastructure_retry_count
                + _consume_infrastructure_retries(context)
            )
            return update
        retry_count = _consume_infrastructure_retries(context)
        top_k = PROBE_SCHEMA_TOP_K
    else:
        if (
            state.schema_snapshot is None
            or state.schema_version is None
        ):
            return _failure_update(_INTERNAL_ERROR)
        snapshot = state.schema_snapshot
        retry_count = 0
        top_k = decision.schema_top_k
    linking_arguments: dict[str, object] = {}
    if context.retrieval_runtime is not None:
        linking_arguments = {
            "datasource_id": context.datasource_id,
            "retrieval_runtime": context.retrieval_runtime,
            "prepared_pool": (
                state.schema_retrieval_pool
                if decision is not None
                else None
            ),
        }
    try:
        result = link_schema(
            state.normalized_question,
            allowed_schemas=state.allowed_schemas,
            allowed_tables=state.allowed_tables,
            snapshot=snapshot,
            top_k=top_k,
            deadline_at=deadline_at,
            clock=context.clock,
            **linking_arguments,  # type: ignore[arg-type]
        )
    except SchemaRetrievalFailure as error:
        cause = error.cause
        public_error = (
            _public_embedding_error(cause)
            if isinstance(cause, EmbeddingProviderError)
            else _EMBEDDING_PUBLIC_ERRORS[
                "EMBEDDING_INVALID_RESPONSE"
            ]
        )
        update = _failure_update(public_error)
        update.update(
            {
                "schema_version": snapshot.schema_version,
                "schema_snapshot": snapshot,
                "retrieval_failure": error.evidence,
            }
        )
        return update
    except EmbeddingProviderError as error:
        return _failure_update(_public_embedding_error(error))
    except EmbeddingIndexBuildError:
        return _failure_update(
            _EMBEDDING_PUBLIC_ERRORS[
                "EMBEDDING_INVALID_RESPONSE"
            ]
        )
    if (
        result.top_k != top_k
        or len(result.candidate_tables) > top_k
        or (
            decision is not None
            and result.schema_version != state.schema_version
        )
        or (
            decision is not None
            and context.retrieval_runtime is not None
            and (
                result.retrieval_version_id
                != state.retrieval_version_id
                or result.retrieval_pool
                is not state.schema_retrieval_pool
            )
        )
    ):
        return _failure_update(_INTERNAL_ERROR)
    if not result.candidate_tables:
        if state.repair_strategy is RepairStrategy.RELINK_SCHEMA:
            update = _failure_update(_INTERNAL_ERROR)
        else:
            update = _failure_update(_NO_SCHEMA_ERROR)
        update["infrastructure_retry_count"] = (
            state.infrastructure_retry_count + retry_count
        )
        return update
    update: NodeUpdate = {
        "candidate_tables": result.candidate_tables,
        "candidate_fields": result.candidate_fields,
        "join_paths": result.join_paths,
        "schema_version": result.schema_version,
        "schema_snapshot": snapshot,
        "retrieval_version_id": result.retrieval_version_id,
        "schema_retrieval_pool": result.retrieval_pool,
        "retrieval_failure": None,
        "infrastructure_retry_count": (
            state.infrastructure_retry_count + retry_count
        ),
        "public_error": None,
    }
    if decision is None:
        update.update(
            {
                "probe_candidate_table_count": len(
                    result.candidate_tables
                ),
                "probe_candidate_field_count": len(
                    result.candidate_fields
                ),
            }
        )
    return update
