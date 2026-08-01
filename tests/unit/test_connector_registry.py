import pytest

from app.connectors.errors import DatabaseConnectorError
from app.connectors.registry import ConnectorRegistry


class _Connector:
    def __init__(
        self,
        name: str,
        events: list[str],
        *,
        close_error: Exception | None = None,
    ) -> None:
        self.name = name
        self.events = events
        self.close_error = close_error

    def execute(self, sql, *, timeout_seconds=None):  # type: ignore[no-untyped-def]
        raise AssertionError("execution is outside registry lifecycle tests")

    def close(self) -> None:
        self.events.append(f"close:{self.name}")
        if self.close_error is not None:
            raise self.close_error


def test_duplicate_id_is_rejected_without_replacing_owned_connector() -> None:
    events: list[str] = []
    registry = ConnectorRegistry()
    first = _Connector("first", events)
    second = _Connector("second", events)
    registry.register("duplicate", first)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("duplicate", second)

    assert registry.get("duplicate") is first


def test_close_all_reverses_order_continues_after_errors_and_hides_driver_details(
) -> None:
    events: list[str] = []
    registry = ConnectorRegistry()
    registry.register(
        "first",
        _Connector("first", events, close_error=RuntimeError("password=secret")),
    )
    registry.register(
        "second",
        _Connector(
            "second",
            events,
            close_error=RuntimeError(
                "postgresql://reader:secret@host/db"
            ),
        ),
    )
    registry.register("third", _Connector("third", events))

    with pytest.raises(DatabaseConnectorError) as captured:
        registry.close_all()

    assert events == ["close:third", "close:second", "close:first"]
    assert captured.value.details.code == "DB_CLOSE_ERROR"
    assert "second" in captured.value.details.public_message
    assert "first" in captured.value.details.public_message
    assert "password" not in captured.value.details.public_message
    assert "secret" not in captured.value.details.public_message
    assert registry.list_datasources() == []
