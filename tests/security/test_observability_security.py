import logging
from unittest.mock import Mock

from app.observability import (
    SafeLoggingTraceSink,
    TracedWorkflowRunner,
    build_trace_record,
)
from app.workflow import (
    FinalStatus,
    SQLTaskState,
    WorkflowContext,
    WorkflowPublicError,
)
from app.connectors.errors import ErrorType


def _failure_state() -> SQLTaskState:
    return SQLTaskState(
        request_id="req-safe",
        trace_id="trace-safe",
        question="postgresql://reader:secret@db/pagila",
        datasource_id="pagila",
        error_type=ErrorType.UNKNOWN,
        public_error=WorkflowPublicError(
            error_type=ErrorType.UNKNOWN,
            code="SAFE_FAILURE",
            public_message="The request failed.",
        ),
        final_status=FinalStatus.FAILED_INTERNAL,
    )


def _context() -> WorkflowContext:
    return WorkflowContext(
        provider=Mock(),
        connector=Mock(),
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        clock=lambda: 0.0,
    )


def test_logging_sink_emits_only_safe_trace_fields(
    caplog,
) -> None:
    logger = logging.getLogger("test.safe.trace")
    sink = SafeLoggingTraceSink(logger)

    with caplog.at_level(logging.INFO, logger="test.safe.trace"):
        sink.emit(build_trace_record(_failure_state()))

    rendered = caplog.text
    assert "trace-safe" in rendered
    assert "SAFE_FAILURE" in rendered
    assert "postgresql://" not in rendered
    assert "secret" not in rendered


def test_sink_exception_logs_fixed_degradation_without_exception(
    caplog,
) -> None:
    class FailingSink:
        def emit(self, record: object) -> None:
            del record
            raise RuntimeError("full prompt and api_key=secret")

    terminal = _failure_state()

    def base_runner(
        state: SQLTaskState,
        *,
        context: WorkflowContext,
    ) -> SQLTaskState:
        del state, context
        return terminal

    runner = TracedWorkflowRunner(base_runner, FailingSink())

    with caplog.at_level(logging.WARNING):
        result = runner(
            SQLTaskState(
                request_id="req",
                trace_id="trace",
                question="q",
                datasource_id="pagila",
            ),
            context=_context(),
        )

    assert result is terminal
    assert "text_to_sql_trace_sink_degraded" in caplog.text
    assert "full prompt" not in caplog.text
    assert "api_key" not in caplog.text
    assert "secret" not in caplog.text
