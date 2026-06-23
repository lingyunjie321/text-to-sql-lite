import json
import logging

from text_to_sql_demo.observability.config import FileLoggingConfig, LoggingConfig
from text_to_sql_demo.observability.logging import configure_logging, get_logger


def test_configure_logging_creates_console_and_json_file_handlers(tmp_path) -> None:
    log_file = tmp_path / "app.log"
    config = LoggingConfig(file=FileLoggingConfig(path=str(log_file)))

    configure_logging(config)
    logger = get_logger("unit")
    logger.info("hello", extra={"event": "unit.event", "api_key": "sk-secret"})

    output = log_file.read_text(encoding="utf-8").strip()
    payload = json.loads(output)
    assert payload["event"] == "unit.event"
    assert payload["message"] == "hello"
    assert payload["api_key"] == "***REDACTED***"


def test_configure_logging_does_not_duplicate_handlers(tmp_path) -> None:
    log_file = tmp_path / "app.log"
    config = LoggingConfig(file=FileLoggingConfig(path=str(log_file)))

    configure_logging(config)
    configure_logging(config)

    package_logger = logging.getLogger("text_to_sql_demo")
    managed_handlers = [
        handler
        for handler in package_logger.handlers
        if getattr(handler, "_text_to_sql_demo_handler", False)
    ]
    assert len(managed_handlers) == 2


def test_configure_logging_disabled_removes_managed_handlers(tmp_path) -> None:
    log_file = tmp_path / "app.log"
    configure_logging(LoggingConfig(file=FileLoggingConfig(path=str(log_file))))

    configure_logging(LoggingConfig(enabled=False))

    package_logger = logging.getLogger("text_to_sql_demo")
    assert not [
        handler
        for handler in package_logger.handlers
        if getattr(handler, "_text_to_sql_demo_handler", False)
    ]

