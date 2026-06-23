from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator

from text_to_sql_demo.sql.dialect import DialectName

RuntimeDriver = Literal["sqlite", "postgresql", "mysql"]
RuntimeMode = Literal["preset", "custom"]


def _has_text(value: str | None) -> bool:
    return value is not None and bool(value.strip())


class RuntimeModelConfig(BaseModel):
    """工作流运行时实际使用的单个模型配置。"""

    provider: str
    model: str
    base_url: str | None = None
    api_key: SecretStr | None = None
    api_key_env: str | None = None
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_model_config(self) -> RuntimeModelConfig:
        """确保运行时模型具备可调用的最小信息。"""
        if not _has_text(self.provider):
            raise ValueError("运行时模型 provider 不能为空")
        if not _has_text(self.model):
            raise ValueError("运行时模型名称不能为空")
        if self.api_key is None and not _has_text(self.api_key_env):
            raise ValueError("运行时模型必须提供 api_key 或 api_key_env")
        return self


class RuntimeModelRoutingConfig(BaseModel):
    """按复杂度路由使用的轻量和强力模型配置。"""

    light: RuntimeModelConfig
    strong: RuntimeModelConfig


class RuntimeDatabaseConfig(BaseModel):
    """工作流运行时实际使用的数据库配置。"""

    driver: RuntimeDriver
    database_url: SecretStr
    target_dialect: DialectName
    display_name: str


class RuntimeConfigDisplay(BaseModel):
    """可返回给前端展示的脱敏运行时配置摘要。"""

    database: str
    models: dict[str, str]


class RuntimeConfig(BaseModel):
    """一次 Text-to-SQL 会话的运行时数据库与模型配置。"""

    id: str
    expires_at: datetime
    database: RuntimeDatabaseConfig
    models: RuntimeModelRoutingConfig
    display: RuntimeConfigDisplay

    @model_validator(mode="after")
    def validate_expires_at(self) -> RuntimeConfig:
        """运行时配置过期时间必须使用带时区的绝对时间。"""
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("expires_at 必须包含时区信息")
        return self


class RuntimePresetSelection(BaseModel):
    """从服务端预设中选择运行时配置。"""

    mode: RuntimeMode = "preset"
    preset_id: str | None = None

    @model_validator(mode="after")
    def validate_preset(self) -> RuntimePresetSelection:
        """preset 模式必须声明可解析的 preset_id。"""
        if self.mode == "preset" and not _has_text(self.preset_id):
            raise ValueError("preset 模式必须提供 preset_id")
        return self


class RuntimeCustomDatabaseInput(BaseModel):
    """用户提交的自定义数据库连接参数。"""

    driver: RuntimeDriver
    sqlite_path: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    database_name: str | None = None
    username: str | None = None
    password: SecretStr | None = None
    target_dialect: DialectName | None = None
    display_name: str | None = None

    @model_validator(mode="after")
    def validate_custom_database(self) -> RuntimeCustomDatabaseInput:
        """按数据库类型校验必需连接字段。"""
        if self.driver == "sqlite":
            if not _has_text(self.sqlite_path):
                raise ValueError("自定义 sqlite 数据库必须提供 sqlite_path")
            return self

        missing_fields: list[str] = []
        if not _has_text(self.host):
            missing_fields.append("host")
        if self.port is None:
            missing_fields.append("port")
        if not _has_text(self.database_name):
            missing_fields.append("database_name")
        if not _has_text(self.username):
            missing_fields.append("username")
        if self.password is None:
            missing_fields.append("password")
        if missing_fields:
            joined = ", ".join(missing_fields)
            raise ValueError(f"自定义服务型数据库缺少字段: {joined}")
        return self


class RuntimeDatabaseSelection(BaseModel):
    """数据库预设或自定义输入二选一。"""

    mode: RuntimeMode
    preset_id: str | None = None
    config: RuntimeCustomDatabaseInput | None = None

    @model_validator(mode="after")
    def validate_database_selection(self) -> RuntimeDatabaseSelection:
        """确保数据库选择与 mode 匹配。"""
        if self.mode == "preset":
            if not _has_text(self.preset_id):
                raise ValueError("数据库 preset 模式必须提供 preset_id")
            if self.config is not None:
                raise ValueError("数据库 preset 模式不能提供 config")
            return self

        if _has_text(self.preset_id):
            raise ValueError("数据库 custom 模式不能提供 preset_id")
        if self.config is None:
            raise ValueError("数据库 custom 模式必须提供 config")
        return self


class RuntimeModelSelection(BaseModel):
    """模型预设或自定义输入二选一。"""

    mode: RuntimeMode
    preset_id: str | None = None
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: SecretStr | None = None
    api_key_env: str | None = None
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_model_selection(self) -> RuntimeModelSelection:
        """确保模型选择与 mode 匹配。"""
        if self.mode == "preset":
            if not _has_text(self.preset_id):
                raise ValueError("模型 preset 模式必须提供 preset_id")
            if any(
                value is not None
                for value in (
                    self.provider,
                    self.model,
                    self.base_url,
                    self.api_key,
                    self.api_key_env,
                )
            ):
                raise ValueError("模型 preset 模式不能提供自定义字段")
            return self

        if _has_text(self.preset_id):
            raise ValueError("模型 custom 模式不能提供 preset_id")

        missing_fields: list[str] = []
        if not _has_text(self.provider):
            missing_fields.append("provider")
        if not _has_text(self.model):
            missing_fields.append("model")
        if self.api_key is None and not _has_text(self.api_key_env):
            missing_fields.append("api_key 或 api_key_env")
        if missing_fields:
            joined = ", ".join(missing_fields)
            raise ValueError(f"自定义模型缺少字段: {joined}")
        return self


class RuntimeModelRoutingSelection(BaseModel):
    """请求阶段的轻量与强力模型选择。"""

    light: RuntimeModelSelection
    strong: RuntimeModelSelection


class RuntimeDatabaseTestRequest(BaseModel):
    """运行时数据库连接测试请求。"""

    database: RuntimeDatabaseSelection


class RuntimeModelTestRequest(BaseModel):
    """运行时模型连接测试请求。"""

    model: RuntimeModelSelection


class RuntimeConfigCreateRequest(BaseModel):
    """创建运行时配置的请求体。"""

    database: RuntimeDatabaseSelection
    models: RuntimeModelRoutingSelection
    ttl_seconds: int = Field(default=3600, gt=0)
