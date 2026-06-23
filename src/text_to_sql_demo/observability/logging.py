from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from text_to_sql_demo.observability.config import LoggingConfig
from text_to_sql_demo.observability.formatter import ConsoleLogFormatter, JsonLogFormatter

PACKAGE_LOGGER_NAME = "text_to_sql_demo"
_HANDLER_MARKER = "_text_to_sql_demo_handler"


def configure_logging(config: LoggingConfig) -> None:
    """根据配置初始化项目 logger。"""
    package_logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    _remove_managed_handlers(package_logger)

    if not config.enabled:
        package_logger.disabled = True
        return

    package_logger.disabled = False
    package_logger.propagate = False
    package_logger.setLevel(_level_number(config.level))

    if config.console.enabled:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(ConsoleLogFormatter())
        console_handler.setLevel(_level_number(config.level))
        setattr(console_handler, _HANDLER_MARKER, True)
        package_logger.addHandler(console_handler)

    if config.file.enabled:
        log_path = Path(config.file.path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            filename=log_path,
            when="midnight",
            backupCount=config.file.backup_count,
            encoding=config.file.encoding,
        )
        file_handler.setFormatter(JsonLogFormatter())
        file_handler.setLevel(_level_number(config.level))
        setattr(file_handler, _HANDLER_MARKER, True)
        package_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """返回项目命名空间下的 logger。"""
    if name == PACKAGE_LOGGER_NAME or name.startswith(f"{PACKAGE_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{PACKAGE_LOGGER_NAME}.{name}")


def _remove_managed_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()


def _level_number(level: str) -> int:
    resolved = logging.getLevelName(level.upper())
    if isinstance(resolved, int):
        return resolved
    return logging.INFO

