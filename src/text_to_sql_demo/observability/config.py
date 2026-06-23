from typing import Literal

from pydantic import BaseModel, Field


class ConsoleLoggingConfig(BaseModel):
    """控制台日志输出配置。"""

    enabled: bool = True
    format: Literal["text"] = "text"


class FileLoggingConfig(BaseModel):
    """本地文件日志输出配置。"""

    enabled: bool = True
    path: str = "logs/app.log"
    format: Literal["json"] = "json"
    rotation: Literal["daily"] = "daily"
    backup_count: int = Field(default=14, ge=0)
    encoding: str = "utf-8"


class LoggingPrivacyConfig(BaseModel):
    """日志隐私和预览策略。"""

    sql_preview: Literal["disabled", "debug_only", "enabled"] = "debug_only"
    prompt_preview: Literal["disabled", "debug_only", "enabled"] = "disabled"
    include_trace_summary: Literal["disabled", "debug_only", "enabled"] = "debug_only"
    include_traceback: Literal["disabled", "debug_only", "enabled"] = "debug_only"
    max_preview_chars: int = Field(default=160, ge=0)
    redact_keys: list[str] = Field(
        default_factory=lambda: [
            "password",
            "token",
            "api_key",
            "secret",
            "authorization",
            "api-key",
            "x-api-key",
        ]
    )


class LoggingConfig(BaseModel):
    """项目日志系统配置。"""

    enabled: bool = True
    level: str = "INFO"
    console: ConsoleLoggingConfig = Field(default_factory=ConsoleLoggingConfig)
    file: FileLoggingConfig = Field(default_factory=FileLoggingConfig)
    privacy: LoggingPrivacyConfig = Field(default_factory=LoggingPrivacyConfig)

