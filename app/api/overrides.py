"""请求级 Override 解析。

将 QueryRequest 中的 model_overrides / datasource_override 安全地应用到
WorkflowContext 上。安全约束：
- api_key / password 绝不写日志或 Trace 明文；
- ad-hoc 数据源默认拒绝（需 TEXT_TO_SQL_ALLOW_ADHOC_DATASOURCES=true）；
- 覆写不绕过任何既有 SQL 安全校验。
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace as dc_replace
from typing import TYPE_CHECKING

from app.api.models import DatasourceOverride, ModelOverride, QueryRequest
from app.config import AuthSettings, LLMRouteSettings, LLMSettings, _LLMRouteOverrideSettings, load_auth_settings
from app.generation import (
    OpenAICompatibleLLMProvider,
    build_configured_model_routing_runtime,
)
from app.workflow import WorkflowContext

if TYPE_CHECKING:
    from app.api.bootstrap import ApplicationServices

_OVERRIDE_TIERS = ("simple", "standard", "complex")


class OverrideError(Exception):
    """请求级覆写被拒绝（返回 400）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _model_override_to_route_settings(
    override: ModelOverride,
) -> _LLMRouteOverrideSettings:
    """将 API 层 ModelOverride 转为配置层覆写对象。"""
    return _LLMRouteOverrideSettings(
        base_url=override.base_url,
        api_key=override.api_key,
        model=override.model_name,
    )


def apply_model_overrides(
    base_context: WorkflowContext,
    model_overrides: dict[str, ModelOverride] | None,
    base_route_settings: LLMRouteSettings | None,
) -> WorkflowContext:
    """对 WorkflowContext 应用请求级模型覆写。

    无覆写或无 base_route_settings 时原样返回。返回新的
    WorkflowContext（frozen dataclass → dataclasses.replace）。
    """
    if not model_overrides or base_route_settings is None:
        return base_context

    unknown_keys = set(model_overrides) - set(_OVERRIDE_TIERS)
    if unknown_keys:
        raise OverrideError(
            f"model_overrides keys must be one of {_OVERRIDE_TIERS}; "
            f"got unknown: {sorted(unknown_keys)}"
        )

    new_simple = base_route_settings.simple
    new_standard = base_route_settings.standard
    new_complex = base_route_settings.complex

    tier_map = {
        "simple": (new_simple, "simple"),
        "standard": (new_standard, "standard"),
        "complex": (new_complex, "complex"),
    }

    changed: dict[str, LLMSettings] = {}
    for tier, override in model_overrides.items():
        base_settings, _ = tier_map[tier]
        route_override = _model_override_to_route_settings(override)
        overlaid, did_change = route_override.overlay(base_settings)
        if did_change:
            changed[tier] = overlaid

    if not changed:
        return base_context

    overrides_kwargs: dict[str, object] = {}
    if "simple" in changed:
        overrides_kwargs["simple"] = changed["simple"]
    if "standard" in changed:
        overrides_kwargs["standard"] = changed["standard"]
    if "complex" in changed:
        overrides_kwargs["complex"] = changed["complex"]

    new_route_settings = dc_replace(
        base_route_settings, **overrides_kwargs
    )

    target_settings = {
        "simple": new_route_settings.simple,
        "standard": new_route_settings.standard,
        "complex": new_route_settings.complex,
    }
    if new_route_settings.fallback is not None:
        target_settings["fallback"] = new_route_settings.fallback

    providers = {
        key: OpenAICompatibleLLMProvider(settings)
        for key, settings in target_settings.items()
    }

    new_routing = build_configured_model_routing_runtime(
        settings=new_route_settings,
        providers=providers,
    )

    return dc_replace(base_context, model_routing=new_routing)


def _has_inline_connection_fields(override: DatasourceOverride) -> bool:
    """判断 DatasourceOverride 是否包含内联连接字段。"""
    return any(
        getattr(override, field) is not None
        for field in (
            "type",
            "host",
            "port",
            "database",
            "username",
            "password",
        )
    )


def resolve_request_context(
    query: QueryRequest,
    services: ApplicationServices,
) -> WorkflowContext:
    """解析请求级上下文：数据源路由 + 模型覆写。

    - datasource_override.datasource_id-only → 路由到已注册数据源。
    - datasource_override 内联连接 → 需 allow_adhoc_datasources 开启。
    - model_overrides → 安全应用模型覆写。
    """
    base_datasource_id = query.datasource_id

    if query.datasource_override is not None:
        ds_override = query.datasource_override

        if ds_override.datasource_id is not None and not _has_inline_connection_fields(ds_override):
            base_datasource_id = ds_override.datasource_id
            base_context = services.context_for(base_datasource_id)
        elif _has_inline_connection_fields(ds_override):
            auth = load_auth_settings()
            if not auth.allow_adhoc_datasources:
                raise OverrideError(
                    "Ad-hoc datasource connections are not permitted. "
                    "Set TEXT_TO_SQL_ALLOW_ADHOC_DATASOURCES=true to enable."
                )
            if ds_override.type not in ("postgresql", "mysql", "starrocks"):
                raise OverrideError(
                    f"Unsupported datasource type: {ds_override.type!r}"
                )
            if not ds_override.schemas or not ds_override.allowed_tables:
                raise OverrideError(
                    "Ad-hoc datasource requires explicit schemas and "
                    "allowed_tables in the override."
                )
            raise OverrideError(
                "Ad-hoc datasource connection is enabled but the ephemeral "
                "connector builder is not yet wired in this build. Use a "
                "registered datasource_id instead."
            )
        else:
            base_context = services.context_for(base_datasource_id)
    else:
        base_context = services.context_for(base_datasource_id)

    base_route_settings = getattr(
        services, "llm_route_settings", None
    )

    return apply_model_overrides(
        base_context,
        query.model_overrides,
        base_route_settings,
    )
