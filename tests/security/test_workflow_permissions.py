from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from app.connectors.errors import ErrorType
from app.workflow import (
    WorkflowContext,
    WorkflowPermissionError,
    resolve_permissions,
)
from tests.routing_support import single_provider_test_routing


def _context() -> WorkflowContext:
    provider = Mock()
    return WorkflowContext(
        connector=Mock(),
        model_routing=single_provider_test_routing(
            provider
        ),
        datasource_id="pagila",
        allowed_schemas=("audit", "public"),
        allowed_tables=(
            "audit.event",
            "public.actor",
            "public.film",
        ),
        now=datetime(2026, 7, 28, tzinfo=timezone.utc),
    )


def test_empty_request_uses_server_allowlist() -> None:
    scope = resolve_permissions(
        datasource_id="pagila",
        requested_schemas=(),
        context=_context(),
    )

    assert scope.allowed_schemas == ("audit", "public")
    assert scope.allowed_tables == (
        "audit.event",
        "public.actor",
        "public.film",
    )


def test_request_can_only_narrow_server_allowlist() -> None:
    scope = resolve_permissions(
        datasource_id="pagila",
        requested_schemas=("public",),
        context=_context(),
    )

    assert scope.allowed_schemas == ("public",)
    assert scope.allowed_tables == (
        "public.actor",
        "public.film",
    )


@pytest.mark.parametrize(
    ("datasource_id", "requested_schemas"),
    [
        ("other", ()),
        ("pagila", ("private",)),
        ("pagila", ("public", "private")),
        ("pagila", ("",)),
    ],
)
def test_overbroad_or_invalid_scope_is_denied(
    datasource_id: str,
    requested_schemas: tuple[str, ...],
) -> None:
    context = _context()

    with pytest.raises(WorkflowPermissionError) as caught:
        resolve_permissions(
            datasource_id=datasource_id,
            requested_schemas=requested_schemas,
            context=context,
        )

    assert caught.value.details.error_type is ErrorType.PERMISSION_DENIED
    assert caught.value.details.code == "WORKFLOW_PERMISSION_DENIED"
    assert "private" not in caught.value.details.public_message
    context.connector.read_metadata.assert_not_called()
    context.model_routing.provider_registry.resolve(
        "test-provider"
    ).provider.generate.assert_not_called()
