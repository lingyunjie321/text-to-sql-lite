"""请求级 Override 接线的单元与安全测试。"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import ApplicationServices, create_app
from app.api.models import DatasourceOverride, ModelOverride, QueryRequest
from app.api.overrides import OverrideError, resolve_request_context
from app.config import LLMRouteSettings, LLMSettings
from app.workflow import WorkflowContext
from tests.routing_support import single_provider_test_routing


def _llm_settings(model: str = "base-model") -> LLMSettings:
    return LLMSettings(
        base_url="https://models.example.test/v1",
        api_key="sk-test-secret-key-123",
        model=model,
    )


def _route_settings() -> LLMRouteSettings:
    return LLMRouteSettings(
        simple=_llm_settings("simple-model"),
        standard=_llm_settings("standard-model"),
        complex=_llm_settings("complex-model"),
        fallback=None,
        fallback_route_ids=(),
        data_boundary_id="test-boundary-v1",
    )


def _mock_context() -> WorkflowContext:
    return WorkflowContext(
        connector=Mock(),
        model_routing=single_provider_test_routing(Mock()),
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        clock=lambda: 0.0,
    )


def _services() -> ApplicationServices:
    return ApplicationServices(
        context=_mock_context(),
        runner=lambda state, *, context: state,
        llm_route_settings=_route_settings(),
    )


class TestModelOverrideValidation:
    """model_overrides tier 键校验。"""

    def test_unknown_tier_key_rejected(self) -> None:
        with pytest.raises(ValidationError, match="model_overrides keys"):
            QueryRequest(
                question="test",
                model_overrides={"evil": ModelOverride(model_name="x")},
            )

    def test_valid_tier_keys_accepted(self) -> None:
        req = QueryRequest(
            question="test",
            model_overrides={
                "simple": ModelOverride(model_name="new-model"),
                "complex": ModelOverride(model_name="strong-model"),
            },
        )
        assert req.model_overrides is not None
        assert set(req.model_overrides) == {"simple", "complex"}

    def test_empty_overrides_accepted(self) -> None:
        req = QueryRequest(question="test", model_overrides=None)
        assert req.model_overrides is None


class TestModelOverrideApplication:
    """model_overrides 应用逻辑。"""

    def test_no_overrides_returns_base_context(self) -> None:
        services = _services()
        query = QueryRequest(question="test")
        ctx = resolve_request_context(query, services)
        assert ctx is services.context

    def test_override_changes_model_routing(self) -> None:
        services = _services()
        query = QueryRequest(
            question="test",
            model_overrides={
                "complex": ModelOverride(model_name="stronger-model"),
            },
        )
        ctx = resolve_request_context(query, services)
        # 新上下文的 model_routing 应不同于原始的
        assert ctx.model_routing is not services.context.model_routing

    def test_override_with_same_values_rebuilds_equivalently(self) -> None:
        """overlay 在字段有值时始终重建（即使值相同），这是 overlay 的契约。"""
        services = _services()
        query = QueryRequest(
            question="test",
            model_overrides={
                "simple": ModelOverride(model_name="simple-model"),
            },
        )
        ctx = resolve_request_context(query, services)
        # 重建了新上下文（overlay 契约：有值即重建）
        assert ctx is not services.context
        # 但 simple tier 的 model 仍然是同一个值
        reg = ctx.model_routing.provider_registry
        assert reg.resolve("simple").provider._settings.model == "simple-model"


class TestDatasourceOverrideSecurity:
    """datasource_override 安全约束。"""

    def test_adhoc_default_denied(self) -> None:
        services = _services()
        query = QueryRequest(
            question="test",
            datasource_override=DatasourceOverride(
                type="postgresql",
                host="evil.example.test",
                port=5432,
                database="target",
                username="attacker",
                password="secret",
                schemas=["public"],
                allowed_tables=["public.users"],
            ),
        )
        with pytest.raises(OverrideError, match="not permitted"):
            resolve_request_context(query, services)

    def test_adhoc_invalid_type_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_SQL_ALLOW_ADHOC_DATASOURCES", "true")
        services = _services()
        query = QueryRequest(
            question="test",
            datasource_override=DatasourceOverride(
                type="mongodb",
                host="evil.example.test",
                port=27017,
                database="target",
                username="attacker",
                password="secret",
                schemas=["public"],
                allowed_tables=["public.users"],
            ),
        )
        with pytest.raises(OverrideError, match="Unsupported datasource type"):
            resolve_request_context(query, services)

    def test_adhoc_missing_allowlist_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEXT_TO_SQL_ALLOW_ADHOC_DATASOURCES", "true")
        services = _services()
        query = QueryRequest(
            question="test",
            datasource_override=DatasourceOverride(
                type="postgresql",
                host="evil.example.test",
                port=5432,
                database="target",
                username="attacker",
                password="secret",
            ),
        )
        with pytest.raises(OverrideError, match="explicit schemas"):
            resolve_request_context(query, services)

    def test_datasource_id_only_routes_to_registered(self) -> None:
        services = _services()
        query = QueryRequest(
            question="test",
            datasource_override=DatasourceOverride(datasource_id="pagila"),
        )
        ctx = resolve_request_context(query, services)
        assert ctx.datasource_id == "pagila"


class TestOverrideApiIntegration:
    """API 层集成：覆写被拒绝时返回结构化错误。"""

    def test_adhoc_returns_400(self) -> None:
        runner = lambda state, *, context: state
        services = ApplicationServices(
            context=_mock_context(),
            runner=runner,
            llm_route_settings=_route_settings(),
        )
        app = create_app(services=services)
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/text-to-sql",
                json={
                    "question": "test",
                    "datasource_override": {
                        "type": "postgresql",
                        "host": "evil.example.test",
                        "port": 5432,
                        "database": "target",
                        "username": "attacker",
                        "password": "secret",
                        "schemas": ["public"],
                        "allowed_tables": ["public.users"],
                    },
                },
            )
        assert response.status_code == 400
        body = response.json()
        assert body["status"] == "REJECTED_SECURITY"
        assert body["error"]["code"] == "OVERRIDE_REJECTED"
        # password 不出现在响应中
        assert "secret" not in response.text

    def test_unknown_tier_key_returns_422(self) -> None:
        services = ApplicationServices(
            context=_mock_context(),
            runner=lambda state, *, context: state,
        )
        app = create_app(services=services)
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/text-to-sql",
                json={
                    "question": "test",
                    "model_overrides": {
                        "evil": {"model_name": "attacker"},
                    },
                },
            )
        assert response.status_code == 422
