import io
import logging

from text_to_sql_demo.observability.context import clear_context, set_request_context
from text_to_sql_demo.observability.formatter import ConsoleLogFormatter


def test_console_formatter_is_human_readable_and_redacts_sensitive_extra() -> None:
    clear_context()
    set_request_context(request_id="req-console")
    stream = io.StringIO()
    logger = logging.getLogger("tests.console_formatter")
    logger.handlers = []
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(ConsoleLogFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.warning(
        "sql validation failed",
        extra={
            "event": "sql.validation.failed",
            "node_name": "sql_validation",
            "password": "secret",
            "sql_error_category": "unknown_column",
        },
    )

    output = stream.getvalue()
    assert "WARNING" in output
    assert "sql.validation.failed" in output
    assert "request_id=req-console" in output
    assert "node=sql_validation" in output
    assert "unknown_column" in output
    assert "secret" not in output
    assert "***REDACTED***" in output

