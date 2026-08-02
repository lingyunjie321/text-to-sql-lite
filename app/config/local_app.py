from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_ENV_FILE = Path(".env")
_LOCAL_APP_DIRECTORY = ".text-to-sql-lite"


def _resolved_env_file(env_file: Path | None) -> Path:
    return _DEFAULT_ENV_FILE if env_file is None else env_file


def default_profile_database_path() -> Path:
    """Return the local Profile database path without creating it."""

    return Path.home() / _LOCAL_APP_DIRECTORY / "config.db"


class AuthSettings(BaseSettings):
    """应用级安全与请求级覆写策略配置。

    ``allow_adhoc_datasources`` 控制是否允许请求体内联
    数据源连接信息。
    生产环境默认关闭，仅在受控调试环境显式开启。
    """

    model_config = SettingsConfigDict(
        env_prefix="TEXT_TO_SQL_",
        extra="ignore",
    )

    api_key: SecretStr | None = None
    debug_key: SecretStr | None = None
    allow_adhoc_datasources: bool = False

    @property
    def api_key_value(self) -> str | None:
        if self.api_key is None:
            return None
        return self.api_key.get_secret_value()

    @property
    def debug_key_value(self) -> str | None:
        if self.debug_key is None:
            return None
        return self.debug_key.get_secret_value()


def load_auth_settings(env_file: Path | None = None) -> AuthSettings:
    return AuthSettings(_env_file=_resolved_env_file(env_file))
