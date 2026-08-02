from __future__ import annotations

import logging
from collections.abc import Callable

import pytest

from app.config import DatabaseSettings
from app.workflow import WorkflowContext
from tests.routing_support import single_provider_test_routing


class _Provider:
    def generate(
        self,
        messages,
        *,
        timeout_seconds=None,
    ):  # type: ignore[no-untyped-def]
        raise AssertionError("generation is outside bootstrap lifecycle tests")


class _Connector:
    def __init__(
        self,
        name: str,
        events: list[str],
        *,
        open_error: Exception | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self.name = name
        self.events = events
        self.open_error = open_error
        self.close_error = close_error

    def open(self) -> None:
        self.events.append(f"open:{self.name}")
        if self.open_error is not None:
            raise self.open_error

    def close(self) -> None:
        self.events.append(f"close:{self.name}")
        if self.close_error is not None:
            raise self.close_error

    def execute(
        self,
        sql,
        *,
        timeout_seconds=None,
    ):  # type: ignore[no-untyped-def]
        raise AssertionError("execution is outside bootstrap lifecycle tests")

    def read_metadata(
        self,
        schemas,
        tables,
        *,
        timeout_seconds=None,
    ):  # type: ignore[no-untyped-def]
        raise AssertionError("metadata is outside bootstrap lifecycle tests")


class _ConnectorFactory:
    def __init__(self, connectors: list[_Connector | Exception]) -> None:
        self._connectors = iter(connectors)

    def create(self, settings: DatabaseSettings) -> _Connector:
        del settings
        created = next(self._connectors)
        if isinstance(created, Exception):
            raise created
        return created


class _ContextFactory:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error

    def create(self, **kwargs) -> WorkflowContext:  # type: ignore[no-untyped-def]
        if self._error is not None:
            raise self._error
        return WorkflowContext(
            connector=kwargs["connector"],
            model_routing=single_provider_test_routing(_Provider()),
            datasource_id=kwargs["datasource_id"],
            allowed_schemas=kwargs["allowed_schemas"],
            allowed_tables=kwargs["allowed_tables"],
        )


class _ModelFactory:
    def create(self, settings):  # type: ignore[no-untyped-def]
        return object()


def _settings(datasource_id: str) -> DatabaseSettings:
    return DatabaseSettings(
        datasource_id=datasource_id,
        dsn="postgresql://reader:secret@127.0.0.1:55432/pagila",
    )


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    *,
    connectors: list[_Connector | Exception],
    primary_id: str = "primary",
    extras: dict[str, DatabaseSettings] | None = None,
    model_factory: object | None = None,
    embedding_builder: Callable[[object], object] | None = None,
    context_factory: _ContextFactory | None = None,
) -> object:
    from app.api import bootstrap

    monkeypatch.setattr(
        bootstrap,
        "load_database_settings",
        lambda: _settings(primary_id),
    )
    monkeypatch.setattr(
        bootstrap,
        "load_datasources_from_file",
        lambda path: extras or {},
    )
    monkeypatch.setattr(
        bootstrap,
        "_get_datasource_allowed_config",
        lambda *args, **kwargs: (("public",), ("public.orders",), "postgresql"),
    )
    monkeypatch.setattr(
        bootstrap,
        "ConnectorFactory",
        lambda: _ConnectorFactory(connectors),
    )
    monkeypatch.setattr(
        bootstrap,
        "ModelProviderFactory",
        lambda: model_factory or _ModelFactory(),
    )
    monkeypatch.setattr(
        bootstrap,
        "load_llm_route_settings",
        lambda: object(),
    )
    monkeypatch.setattr(
        bootstrap,
        "load_embedding_settings",
        lambda: object(),
    )
    monkeypatch.setattr(
        bootstrap,
        "OpenAICompatibleEmbeddingProvider",
        embedding_builder or (lambda settings: object()),
    )
    monkeypatch.setattr(
        bootstrap,
        "WorkflowContextFactory",
        lambda: context_factory or _ContextFactory(),
    )
    monkeypatch.setattr(
        bootstrap,
        "LocalProfileStore",
        lambda: object(),
    )
    return bootstrap.ApplicationBootstrap()


def test_constructor_failure_has_no_connector_to_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup_error = RuntimeError("postgresql://reader:password@host/private")
    bootstrap = _configure(monkeypatch, connectors=[startup_error])

    from app.api.bootstrap import ApplicationBootstrapError

    with pytest.raises(ApplicationBootstrapError) as captured:
        bootstrap.build()  # type: ignore[attr-defined]

    assert captured.value.code == "APP_BOOTSTRAP_FAILED"
    assert captured.value.stage == "connector"
    assert "postgresql://" not in str(captured.value)
    assert "password" not in repr(captured.value)


def test_open_failure_closes_connector_already_taken_into_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connector = _Connector(
        "first",
        events,
        open_error=RuntimeError("driver private error"),
    )
    bootstrap = _configure(monkeypatch, connectors=[connector])

    from app.api.bootstrap import ApplicationBootstrapError

    with pytest.raises(ApplicationBootstrapError) as captured:
        bootstrap.build()  # type: ignore[attr-defined]

    assert events == ["open:first", "close:first"]
    assert captured.value.stage == "connector"
    assert "private" not in str(captured.value)


def test_keyboard_interrupt_closes_owned_connector_before_reraising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connector = _Connector(
        "first",
        events,
        open_error=KeyboardInterrupt(),
    )
    bootstrap = _configure(monkeypatch, connectors=[connector])

    with pytest.raises(KeyboardInterrupt):
        bootstrap.build()  # type: ignore[attr-defined]

    assert events == ["open:first", "close:first"]


def test_second_open_failure_closes_connectors_in_reverse_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    first = _Connector("first", events)
    second = _Connector("second", events, open_error=RuntimeError("open failed"))
    bootstrap = _configure(
        monkeypatch,
        connectors=[first, second],
        extras={"second": _settings("second")},
    )

    from app.api.bootstrap import ApplicationBootstrapError

    with pytest.raises(ApplicationBootstrapError) as captured:
        bootstrap.build()  # type: ignore[attr-defined]

    assert events == [
        "open:first",
        "open:second",
        "close:second",
        "close:first",
    ]
    assert captured.value.stage == "connector"


def test_duplicate_datasource_id_is_rejected_and_closes_owned_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    first = _Connector("first", events)
    bootstrap = _configure(
        monkeypatch,
        connectors=[first],
        primary_id="duplicate",
        extras={"duplicate": _settings("duplicate")},
    )

    from app.api.bootstrap import ApplicationBootstrapError

    with pytest.raises(ApplicationBootstrapError) as captured:
        bootstrap.build()  # type: ignore[attr-defined]

    assert events == ["open:first", "close:first"]
    assert captured.value.stage == "configuration"


def test_registration_failure_closes_connector_taken_into_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import bootstrap as bootstrap_module

    events: list[str] = []
    connector = _Connector("first", events)

    class _RejectingRegistry:
        def register(self, datasource_id: str, connector: _Connector) -> None:
            del datasource_id, connector
            raise ValueError("datasource registration failed")

    bootstrap = _configure(monkeypatch, connectors=[connector])
    monkeypatch.setattr(
        bootstrap_module,
        "ConnectorRegistry",
        _RejectingRegistry,
    )

    from app.api.bootstrap import ApplicationBootstrapError

    with pytest.raises(ApplicationBootstrapError) as captured:
        bootstrap.build()  # type: ignore[attr-defined]

    assert events == ["close:first"]
    assert captured.value.stage == "connector"


def test_pagila_semantic_failure_closes_raw_connector_before_model_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import bootstrap as bootstrap_module

    events: list[str] = []
    connector = _Connector("pagila", events)

    class _ModelFactory:
        def create(self, settings):  # type: ignore[no-untyped-def]
            raise AssertionError("model factory must not run after semantic failure")

    bootstrap = _configure(
        monkeypatch,
        connectors=[connector],
        primary_id="pagila",
        model_factory=_ModelFactory(),
    )
    monkeypatch.setattr(
        bootstrap_module,
        "_setup_pagila_connector",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad manifest")),
    )

    from app.api.bootstrap import ApplicationBootstrapError

    with pytest.raises(ApplicationBootstrapError) as captured:
        bootstrap.build()  # type: ignore[attr-defined]

    assert events == ["open:pagila", "close:pagila"]
    assert captured.value.stage == "connector"


@pytest.mark.parametrize("failure_step", ("model", "embedding", "context"))
def test_shared_setup_failure_closes_open_connector(
    monkeypatch: pytest.MonkeyPatch,
    failure_step: str,
) -> None:
    events: list[str] = []
    connector = _Connector("first", events)

    class _FailingModelFactory:
        def create(self, settings):  # type: ignore[no-untyped-def]
            raise ValueError("model configuration invalid")

    def failing_embedding(settings: object) -> object:
        raise ValueError("embedding configuration invalid")

    bootstrap = _configure(
        monkeypatch,
        connectors=[connector],
        model_factory=_FailingModelFactory() if failure_step == "model" else None,
        embedding_builder=failing_embedding if failure_step == "embedding" else None,
        context_factory=(
            _ContextFactory(error=ValueError("context invalid"))
            if failure_step == "context"
            else None
        ),
    )

    from app.api.bootstrap import ApplicationBootstrapError

    with pytest.raises(ApplicationBootstrapError) as captured:
        bootstrap.build()  # type: ignore[attr-defined]

    assert events == ["open:first", "close:first"]
    assert captured.value.stage == failure_step


def test_successful_services_close_all_registered_connectors_in_reverse_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    first = _Connector("first", events)
    second = _Connector("second", events)
    bootstrap = _configure(
        monkeypatch,
        connectors=[first, second],
        extras={"second": _settings("second")},
    )

    services = bootstrap.build()  # type: ignore[attr-defined]

    assert services.close is not None
    services.close()
    assert events == [
        "open:first",
        "open:second",
        "close:second",
        "close:first",
    ]


@pytest.mark.parametrize("failure_step", ("runner", "services"))
def test_service_assembly_failure_closes_open_connector(
    monkeypatch: pytest.MonkeyPatch,
    failure_step: str,
) -> None:
    from app.api import bootstrap as bootstrap_module
    from app.api.bootstrap import ApplicationBootstrapError

    events: list[str] = []
    connector = _Connector("first", events)
    bootstrap = _configure(monkeypatch, connectors=[connector])
    if failure_step == "runner":
        monkeypatch.setattr(
            bootstrap_module,
            "default_traced_runner",
            lambda: (_ for _ in ()).throw(RuntimeError("api-key=secret")),
        )
    else:
        monkeypatch.setattr(
            bootstrap_module,
            "ApplicationServices",
            lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError("postgresql://reader:password@host/db")
            ),
        )

    with pytest.raises(ApplicationBootstrapError) as captured:
        bootstrap.build()  # type: ignore[attr-defined]

    assert events == ["open:first", "close:first"]
    assert captured.value.stage == failure_step
    assert "secret" not in str(captured.value)
    assert "password" not in repr(captured.value)


def test_cleanup_closes_every_connector_and_logs_only_fixed_event(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.api.bootstrap import ApplicationBootstrapError

    events: list[str] = []
    first = _Connector(
        "first",
        events,
        close_error=RuntimeError("password=first-secret"),
    )
    second = _Connector(
        "second",
        events,
        close_error=RuntimeError("postgresql://reader:second-secret@host/db"),
    )

    class _FailingModelFactory:
        def create(self, settings):  # type: ignore[no-untyped-def]
            raise ValueError("api-key=model-secret")

    bootstrap = _configure(
        monkeypatch,
        connectors=[first, second],
        extras={"second": _settings("second")},
        model_factory=_FailingModelFactory(),
    )
    caplog.set_level(logging.WARNING, logger="app.api.bootstrap")

    with pytest.raises(ApplicationBootstrapError) as captured:
        bootstrap.build()  # type: ignore[attr-defined]

    assert events == ["open:first", "open:second", "close:second", "close:first"]
    assert captured.value.stage == "model"
    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert rendered == (
        "bootstrap_connector_close_failed\n"
        "bootstrap_connector_close_failed"
    )
    for secret in ("first-secret", "second-secret", "model-secret", "password"):
        assert secret not in rendered
        assert secret not in str(captured.value)
