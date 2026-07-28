from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from app.connectors.errors import (
    DatabaseError,
    ErrorType,
    PostgreSQLConnectorError,
)
from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.connectors.models import ExecutionResult
from app.generation import (
    GenerationResult,
    GeneratedSQL,
    LLMError,
    LLMMessage,
    LLMProviderError,
)
from app.workflow import (
    FinalStatus,
    WorkflowContext,
    new_task_state,
    run_workflow,
)


SNAPSHOT = build_schema_snapshot(
    tables=(
        TableMetadata(
            schema_name="public",
            table_name="film",
            relation_kind="table",
            comment=None,
            columns=(
                ColumnMetadata(
                    schema_name="public",
                    table_name="film",
                    column_name="film_id",
                    ordinal_position=1,
                    data_type="int4",
                    formatted_type="integer",
                    nullable=False,
                    comment=None,
                ),
            ),
        ),
    ),
    primary_keys=(),
    foreign_keys=(),
    unique_constraints=(),
    unique_indexes=(),
)


@dataclass
class Provider:
    sql: str

    def __post_init__(self) -> None:
        self.calls: list[tuple[LLMMessage, ...]] = []

    def generate(
        self,
        messages: Sequence[LLMMessage],
    ) -> GenerationResult:
        self.calls.append(tuple(messages))
        return GenerationResult(
            output=GeneratedSQL(sql=self.sql),
            input_tokens=1,
            output_tokens=1,
            model="stub-model",
            prompt_version="mvp-v1",
        )


@dataclass
class Connector:
    error: DatabaseError | None = None

    def __post_init__(self) -> None:
        self.metadata_calls = 0
        self.execute_calls: list[str] = []

    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
    ):
        self.metadata_calls += 1
        return SNAPSHOT

    def execute(self, sql: str) -> ExecutionResult:
        self.execute_calls.append(sql)
        if self.error is not None:
            raise PostgreSQLConnectorError(self.error)
        raise AssertionError("unsafe SQL reached the connector")


def _run(
    sql: str,
    *,
    error: DatabaseError | None = None,
):
    provider = Provider(sql)
    connector = Connector(error)
    result = run_workflow(
        new_task_state(
            request_id="req-security",
            trace_id="trace-security",
            question="List film identifiers",
            datasource_id="pagila",
        ),
        context=WorkflowContext(
            provider=provider,
            connector=connector,
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=("public.film",),
            clock=lambda: 0.0,
        ),
    )
    return result, provider, connector


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM film",
        "SELECT film_id FROM film; SELECT 1",
        "SELECT pg_sleep(1) FROM film",
    ],
)
def test_security_rejections_have_zero_execution_and_zero_repair(
    sql: str,
) -> None:
    result, provider, connector = _run(sql)

    assert result.final_status is FinalStatus.REJECTED_SECURITY
    assert result.error_type is ErrorType.PERMISSION_DENIED
    assert len(provider.calls) == 1
    assert connector.execute_calls == []
    assert result.repair_count == 0


@pytest.mark.parametrize(
    ("error_type", "status"),
    [
        (ErrorType.CONNECTION_ERROR, FinalStatus.FAILED_CONNECTION),
        (ErrorType.TIMEOUT, FinalStatus.FAILED_TIMEOUT),
    ],
)
def test_infrastructure_errors_never_call_llm_repair(
    error_type: ErrorType,
    status: FinalStatus,
) -> None:
    error = DatabaseError(
        sqlstate="08006" if error_type is ErrorType.CONNECTION_ERROR else "57014",
        error_type=error_type,
        code="SAFE_CODE",
        retryable=False,
        public_message="A safe public message.",
    )
    result, provider, connector = _run(
        "SELECT film_id FROM film LIMIT 1",
        error=error,
    )

    assert result.final_status is status
    assert len(provider.calls) == 1
    assert len(connector.execute_calls) == 1
    assert result.repair_count == 0


def test_model_timeout_is_terminal_and_never_reaches_execution() -> None:
    class TimeoutProvider:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            messages: Sequence[LLMMessage],
        ) -> GenerationResult:
            self.calls += 1
            raise LLMProviderError(
                LLMError(
                    error_type=ErrorType.TIMEOUT,
                    code="LLM_TIMEOUT",
                    retryable=False,
                    public_message="The model request timed out.",
                )
            )

    provider = TimeoutProvider()
    connector = Connector()
    result = run_workflow(
        new_task_state(
            request_id="req-model-timeout",
            trace_id="trace-model-timeout",
            question="List film identifiers",
            datasource_id="pagila",
        ),
        context=WorkflowContext(
            provider=provider,
            connector=connector,
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=("public.film",),
            clock=lambda: 0.0,
        ),
    )

    assert result.final_status is FinalStatus.FAILED_TIMEOUT
    assert provider.calls == 1
    assert connector.execute_calls == []
    assert result.repair_count == 0
