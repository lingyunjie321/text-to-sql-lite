from __future__ import annotations

from datetime import UTC, datetime

from text_to_sql_demo.runtime.models import RuntimeConfig


class RuntimeConfigStore:
    """保存短生命周期运行时配置的内存存储。"""

    def __init__(self) -> None:
        self._configs: dict[str, RuntimeConfig] = {}

    def save(self, config: RuntimeConfig) -> None:
        """写入或覆盖同 id 的运行时配置。"""
        self._configs[config.id] = config

    def get(self, config_id: str, now: datetime | None = None) -> RuntimeConfig | None:
        """读取未过期配置；不存在或过期时返回 None。"""
        config = self.get_raw(config_id)
        if config is None:
            return None

        current_time = now or datetime.now(UTC)
        if config.expires_at <= current_time:
            return None
        return config

    def get_raw(self, config_id: str) -> RuntimeConfig | None:
        """读取原始配置，不做过期过滤。"""
        return self._configs.get(config_id)

    def prune_expired(self, now: datetime | None = None) -> int:
        """删除所有过期配置并返回删除数量。"""
        current_time = now or datetime.now(UTC)
        expired_ids = [
            config_id
            for config_id, config in self._configs.items()
            if config.expires_at <= current_time
        ]
        for config_id in expired_ids:
            del self._configs[config_id]
        return len(expired_ids)
