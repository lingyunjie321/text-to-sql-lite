"""按 DatasourceProfile 缓存并释放动态数据库运行时。"""

from __future__ import annotations

import logging
import threading

from app.local.credential_store import InMemoryCredentialStore
from app.local.datasource_runtime import (
    DatasourceRuntime,
    DatasourceRuntimeError,
    DatasourceRuntimeService,
)
from app.local.profile_models import DatasourceProfile

logger = logging.getLogger(__name__)


class RuntimeRegistry:
    """线程安全地懒创建、复用和关闭动态数据源运行时。"""

    def __init__(
        self,
        *,
        runtime_service: DatasourceRuntimeService,
        credential_store: InMemoryCredentialStore,
    ) -> None:
        self._runtime_service = runtime_service
        self._credential_store = credential_store
        self._runtimes: dict[str, DatasourceRuntime] = {}
        self._lock = threading.RLock()

    def get_or_create(
        self,
        profile: DatasourceProfile,
    ) -> DatasourceRuntime:
        with self._lock:
            credentials = self._credential_store.get_datasource(profile.id)
            if credentials is None or credentials.password is None:
                cached = self._runtimes.pop(profile.id, None)
                if cached is not None:
                    self._close_runtime(profile.id, cached)
                raise DatasourceRuntimeError(
                    code="DATASOURCE_CREDENTIAL_MISSING",
                    public_message=(
                        "The datasource password is not available."
                    ),
                    status_code=409,
                )

            cached = self._runtimes.get(profile.id)
            if (
                cached is not None
                and _runtime_identity(cached.profile)
                == _runtime_identity(profile)
            ):
                return cached
            if cached is not None:
                self._runtimes.pop(profile.id, None)
                self._close_runtime(profile.id, cached)

            runtime = self._runtime_service.build_runtime(
                profile,
                credentials.password,
            )
            if runtime.profile != profile:
                self._close_runtime(profile.id, runtime)
                raise DatasourceRuntimeError(
                    code="DATASOURCE_RUNTIME_UNAVAILABLE",
                    public_message=(
                        "The datasource runtime is unavailable."
                    ),
                    status_code=503,
                )
            self._runtimes[profile.id] = runtime
            return runtime

    def invalidate(self, profile_id: str) -> None:
        with self._lock:
            runtime = self._runtimes.pop(profile_id, None)
            if runtime is not None:
                self._close_runtime(profile_id, runtime)

    def close_all(self) -> None:
        with self._lock:
            runtimes = tuple(self._runtimes.items())
            self._runtimes.clear()
            for profile_id, runtime in reversed(runtimes):
                self._close_runtime(profile_id, runtime)

    @staticmethod
    def _close_runtime(
        profile_id: str,
        runtime: DatasourceRuntime,
    ) -> None:
        try:
            runtime.connector.close()
        except Exception:
            logger.warning(
                "datasource_runtime_close_failed",
                extra={"datasource_profile_id": profile_id},
            )


def _runtime_identity(profile: DatasourceProfile) -> tuple[object, ...]:
    return (
        profile.database_type,
        profile.host.casefold(),
        profile.port,
        profile.database,
        profile.username,
        tuple(sorted(profile.allowed_schemas)),
        tuple(sorted(profile.allowed_tables)),
    )
