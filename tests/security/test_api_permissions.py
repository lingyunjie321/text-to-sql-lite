from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.api import (
    ApplicationServices,
    RequestIdentity,
    create_app,
    default_request_identity,
)
from app.connectors.errors import ErrorType
from app.workflow import (
    FinalStatus,
    SQLTaskState,
    WorkflowContext,
    WorkflowPublicError,
    run_workflow,
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
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        clock=lambda: 0.0,
    )


def _ids():
    values = iter(("req-security", "trace-security"))
    return lambda: next(values)


def test_untrusted_debug_is_denied_before_workflow() -> None:
    runner = Mock()
    app = create_app(
        services=ApplicationServices(
            context=_context(),
            runner=runner,
        ),
        id_factory=_ids(),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            headers={"X-Debug-Allowed": "true"},
            json={"question": "List films", "debug": True},
        )

    assert response.status_code == 403
    assert response.json()["status"] == "REJECTED_SECURITY"
    assert response.json()["error"] == {
        "error_type": "PERMISSION_DENIED",
        "code": "API_DEBUG_FORBIDDEN",
        "message": "The request is not permitted.",
    }
    runner.assert_not_called()


def test_only_trusted_dependency_can_authorize_debug() -> None:
    runner = Mock()

    def terminal_failure(
        state: SQLTaskState,
        *,
        context: WorkflowContext,
    ) -> SQLTaskState:
        del context
        runner(state)
        return SQLTaskState(
            request_id=state.request_id,
            trace_id=state.trace_id,
            question=state.question,
            datasource_id=state.datasource_id,
            error_type=ErrorType.UNKNOWN,
            public_error=WorkflowPublicError(
                error_type=ErrorType.UNKNOWN,
                code="SAFE_FAILURE",
                public_message="The request failed.",
            ),
            final_status=FinalStatus.FAILED_INTERNAL,
        )

    app = create_app(
        services=ApplicationServices(
            context=_context(),
            runner=terminal_failure,
        ),
        id_factory=_ids(),
    )
    app.dependency_overrides[default_request_identity] = (
        lambda: RequestIdentity(
            subject="trusted-test-user",
            can_debug=True,
        )
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={"question": "List films", "debug": True},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "FAILED_INTERNAL"
    runner.assert_called_once()


def test_unknown_datasource_and_schema_expansion_call_no_dependencies() -> None:
    for payload in (
        {
            "question": "List films",
            "datasource_id": "other",
        },
        {
            "question": "List films",
            "schemas": ["private"],
        },
    ):
        context = _context()
        app = create_app(
            services=ApplicationServices(
                context=context,
                runner=run_workflow,
            ),
            id_factory=_ids(),
        )

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/text-to-sql",
                json=payload,
            )

        body = response.json()
        assert response.status_code == 200
        assert body["status"] == "REJECTED_SECURITY"
        assert body["sql"] is None
        assert "private" not in str(body)
        context.model_routing.provider_registry.resolve(
            "test-provider"
        ).provider.generate.assert_not_called()
        context.connector.read_metadata.assert_not_called()
        context.connector.execute.assert_not_called()


def test_request_cannot_inject_allowlist_or_dependencies() -> None:
    runner = Mock()
    app = create_app(
        services=ApplicationServices(
            context=_context(),
            runner=runner,
        )
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={
                "question": "List films",
                "allowed_tables": ["public.staff"],
                "provider": "attacker",
            },
        )

    assert response.status_code == 422
    runner.assert_not_called()


def test_invalid_request_response_does_not_echo_sensitive_input() -> None:
    runner = Mock()
    app = create_app(
        services=ApplicationServices(
            context=_context(),
            runner=runner,
        )
    )
    sensitive_input = "private-question-" + ("x" * 2000)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={"question": sensitive_input},
        )

    assert response.status_code == 422
    assert sensitive_input not in response.text
    assert "private-question" not in response.text
    runner.assert_not_called()


def test_runner_exception_returns_fixed_error_without_secrets() -> None:
    def failing_runner(
        state: SQLTaskState,
        *,
        context: WorkflowContext,
    ) -> SQLTaskState:
        del state, context
        raise RuntimeError(
            "postgresql://reader:secret@db/pagila full prompt"
        )

    app = create_app(
        services=ApplicationServices(
            context=_context(),
            runner=failing_runner,
        ),
        id_factory=_ids(),
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={"question": "List films"},
        )

    rendered = response.text
    assert response.status_code == 500
    assert response.json()["status"] == "FAILED_INTERNAL"
    assert response.json()["error"]["code"] == "API_INTERNAL_ERROR"
    assert "secret" not in rendered
    assert "prompt" not in rendered.casefold()
    assert "RuntimeError" not in rendered
