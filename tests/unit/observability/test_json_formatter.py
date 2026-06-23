import io
import json
import logging

from text_to_sql_demo.observability.context import clear_context, set_request_context
from text_to_sql_demo.observability.formatter import JsonLogFormatter


def test_json_formatter_includes_context_source_and_redacted_extra() -> None:
    clear_context()
    set_request_context(request_id="req-json")
    stream = io.StringIO()
    logger = logging.getLogger("tests.json_formatter.context")
    logger.handlers = []
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.info(
        "configured",
        extra={
            "event": "llm.client.configured",
            "provider": "openai_compatible",
            "api_key": "sk-secret",
        },
    )

    payload = json.loads(stream.getvalue())
    assert payload["event"] == "llm.client.configured"
    assert payload["request_id"] == "req-json"
    assert payload["provider"] == "openai_compatible"
    assert payload["api_key"] == "***REDACTED***"
    assert payload["source_file"].endswith("test_json_formatter.py")
    assert payload["source_function"] == (
        "test_json_formatter_includes_context_source_and_redacted_extra"
    )
    assert isinstance(payload["source_line"], int)


def test_json_formatter_records_exception_raise_location() -> None:
    clear_context()
    stream = io.StringIO()
    logger = logging.getLogger("tests.json_formatter.exception")
    logger.handlers = []
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    try:
        _raise_formatter_error()
    except RuntimeError:
        logger.exception("node failed", extra={"event": "workflow.node.failed"})

    payload = json.loads(stream.getvalue())
    assert payload["error_type"] == "RuntimeError"
    assert payload["error_message"] == "formatter boom"
    assert payload["error_file"].endswith("test_json_formatter.py")
    assert payload["error_function"] == "_raise_formatter_error"
    assert isinstance(payload["error_line"], int)


def _raise_formatter_error() -> None:
    raise RuntimeError("formatter boom")
