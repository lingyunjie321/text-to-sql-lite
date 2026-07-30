from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from app.config import EmbeddingSettings
from app.generation import (
    CONTEXT_ESTIMATOR_VERSION,
    CONTEXT_INPUT_BUDGET_DENOMINATOR,
    CONTEXT_INPUT_BUDGET_NUMERATOR,
    ModelRoutingRuntime,
)
from app.schema_linking import (
    BM25_B,
    BM25_K1,
    EMBEDDING_PROVIDER_CONTRACT_VERSION,
    FUSION_VERSION,
    INDEX_EMBEDDING_BATCH_SIZE,
    INDEX_MAX_ENTRIES,
    PROBE_SCHEMA_TOP_K,
    RERANK_VERSION,
    RETRIEVAL_CANDIDATE_LIMIT,
    RETRIEVAL_VERSION_CONTRACT,
    SCHEMA_DOCUMENT_VERSION,
    RetrievalRuntime,
    embedding_endpoint_identity_sha256,
    embedding_provider_config_sha256,
)
from app.schema_linking.models import BM25_VERSION, RRF_K
from app.workflow.complexity import COMPLEXITY_POLICY_VERSION

_CONTROLLED_DIRECTORIES = ("app", "evaluation")
_CONTROLLED_FILES = (
    "pyproject.toml",
    "tools/__init__.py",
    "tools/freeze_view_semantics.py",
    "tools/run_pagila_evaluation.py",
)
_EXCLUDED_DIRECTORIES = frozenset({"__pycache__", "reports"})
_STAGE1_CONFIGURATION_KEYS = frozenset(
    {
        "complexity",
        "retrieval",
        "embedding",
        "rerank",
        "context",
        "model_routing",
    }
)
_SECRET_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "access_token",
    "auth_token",
)
_STAGE1_RETRIEVAL_KEYS = frozenset(
    {
        "retrieval_version_contract",
        "document_version",
        "bm25_version",
        "bm25_k1",
        "bm25_b",
        "candidate_limit",
        "fusion_version",
        "rrf_k",
        "index_max_entries",
        "index_embedding_batch_size",
        "semantic_version",
    }
)
_STAGE1_EMBEDDING_KEYS = frozenset(
    {
        "provider_contract",
        "model",
        "dimension",
        "endpoint_identity_sha256",
        "timeout_seconds",
        "max_batch_documents",
        "max_response_bytes",
    }
)
_STAGE1_TARGET_KEYS = frozenset(
    {
        "model_config_sha256",
        "max_input_tokens",
        "max_output_tokens",
        "timeout_seconds",
        "data_boundary_sha256",
        "output_contract_version",
    }
)


def _controlled_paths(root: Path) -> tuple[Path, ...]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("controlled code tree is invalid")
    paths: list[Path] = []
    try:
        for relative in _CONTROLLED_DIRECTORIES:
            directory = root / relative
            if not directory.is_dir() or directory.is_symlink():
                raise ValueError("controlled code tree is invalid")
            for path in directory.rglob("*"):
                if path.is_symlink():
                    raise ValueError("controlled code tree is invalid")
                local_parts = path.relative_to(directory).parts
                if any(
                    part in _EXCLUDED_DIRECTORIES
                    for part in local_parts
                ):
                    continue
                if path.is_file() and path.suffix == ".py":
                    paths.append(path)
        for relative in _CONTROLLED_FILES:
            path = root / relative
            if (
                not path.is_file()
                or path.is_symlink()
                or path.suffix not in {".py", ".toml"}
            ):
                raise ValueError("controlled code tree is invalid")
            paths.append(path)
    except OSError:
        raise ValueError("controlled code tree is invalid") from None
    return tuple(
        sorted(
            set(paths),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )


def controlled_code_sha256(root: Path) -> str:
    paths = _controlled_paths(root)
    digest = hashlib.sha256()
    domain = b"stage10-controlled-code-v1"
    digest.update(len(domain).to_bytes(4, "big"))
    digest.update(domain)
    digest.update(len(paths).to_bytes(8, "big"))
    try:
        for path in paths:
            if path.is_symlink():
                raise OSError
            relative = path.relative_to(root).as_posix().encode("utf-8")
            content = path.read_bytes()
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
    except (OSError, UnicodeEncodeError, ValueError):
        raise ValueError("controlled code tree is invalid") from None
    return digest.hexdigest()


def evaluation_baseline_id(payload: Mapping[str, object]) -> str:
    if "evaluation_baseline_id" in payload:
        raise ValueError("evaluation baseline payload is invalid")
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise ValueError(
            "evaluation baseline payload is invalid"
        ) from None
    domain = b"stage10-evaluation-baseline-v1"
    framed = (
        len(domain).to_bytes(4, "big")
        + domain
        + len(encoded).to_bytes(8, "big")
        + encoded
    )
    return hashlib.sha256(framed).hexdigest()


def _stage1_json_value(
    value: object,
) -> None | bool | int | float | str | list[object] | dict[str, object]:
    if value is None or type(value) in (bool, int, str):
        return value  # type: ignore[return-value]
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError
        return value
    if isinstance(value, (tuple, list)):
        return [_stage1_json_value(item) for item in value]
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if (
                not isinstance(key, str)
                or not key
                or key != key.strip()
                or any(
                    fragment in key.casefold()
                    for fragment in _SECRET_KEY_FRAGMENTS
                )
            ):
                raise ValueError
            normalized[key] = _stage1_json_value(item)
        return normalized
    raise ValueError


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(
            character in "0123456789abcdef"
            for character in value
        )
    )


def _exact_mapping(
    value: object,
    keys: frozenset[str],
) -> dict[str, object]:
    if not isinstance(value, dict) or frozenset(value) != keys:
        raise ValueError
    return value


def _validate_stage1_target(value: object) -> dict[str, object]:
    target = _exact_mapping(value, _STAGE1_TARGET_KEYS)
    if (
        not _valid_sha256(target["model_config_sha256"])
        or not _valid_sha256(target["data_boundary_sha256"])
        or type(target["max_input_tokens"]) is not int
        or type(target["max_output_tokens"]) is not int
        or target["max_input_tokens"] <= 0  # type: ignore[operator]
        or target["max_output_tokens"] <= 0  # type: ignore[operator]
        or target["max_output_tokens"]  # type: ignore[operator]
        >= target["max_input_tokens"]
        or type(target["timeout_seconds"]) not in (int, float)
        or target["timeout_seconds"] <= 0  # type: ignore[operator]
        or target["timeout_seconds"] > 120  # type: ignore[operator]
        or target["output_contract_version"]
        != "openai-compatible-json-v1"
    ):
        raise ValueError
    return target


def _validate_stage1_configuration_shape(
    value: object,
) -> None:
    root = _exact_mapping(value, _STAGE1_CONFIGURATION_KEYS)
    complexity = _exact_mapping(
        root["complexity"],
        frozenset(
            {
                "policy_version",
                "probe_top_k",
                "simple_top_k",
                "medium_top_k",
                "complex_top_k",
            }
        ),
    )
    if (
        not isinstance(complexity["policy_version"], str)
        or not complexity["policy_version"]
        or (
            complexity["probe_top_k"],
            complexity["simple_top_k"],
            complexity["medium_top_k"],
            complexity["complex_top_k"],
        )
        != (20, 5, 10, 20)
    ):
        raise ValueError

    retrieval = _exact_mapping(
        root["retrieval"],
        _STAGE1_RETRIEVAL_KEYS,
    )
    if (
        any(
            not isinstance(retrieval[key], str)
            or not retrieval[key]
            for key in (
                "retrieval_version_contract",
                "document_version",
                "bm25_version",
                "fusion_version",
                "semantic_version",
            )
        )
        or type(retrieval["bm25_k1"]) not in (int, float)
        or type(retrieval["bm25_b"]) not in (int, float)
        or retrieval["bm25_k1"] <= 0  # type: ignore[operator]
        or not 0 <= retrieval["bm25_b"] <= 1  # type: ignore[operator]
        or type(retrieval["candidate_limit"]) is not int
        or not 1 <= retrieval["candidate_limit"] <= 20  # type: ignore[operator]
        or type(retrieval["rrf_k"]) is not int
        or retrieval["rrf_k"] <= 0  # type: ignore[operator]
        or type(retrieval["index_max_entries"]) is not int
        or retrieval["index_max_entries"] <= 0  # type: ignore[operator]
        or type(retrieval["index_embedding_batch_size"]) is not int
        or retrieval["index_embedding_batch_size"] <= 0  # type: ignore[operator]
    ):
        raise ValueError

    embedding = _exact_mapping(
        root["embedding"],
        _STAGE1_EMBEDDING_KEYS,
    )
    if (
        any(
            not isinstance(embedding[key], str)
            or not embedding[key]
            for key in ("provider_contract", "model")
        )
        or not _valid_sha256(
            embedding["endpoint_identity_sha256"]
        )
        or type(embedding["dimension"]) is not int
        or embedding["dimension"] <= 0  # type: ignore[operator]
        or type(embedding["timeout_seconds"])
        not in (int, float)
        or embedding["timeout_seconds"] <= 0  # type: ignore[operator]
        or type(embedding["max_batch_documents"]) is not int
        or embedding["max_batch_documents"] <= 0  # type: ignore[operator]
        or type(embedding["max_response_bytes"]) is not int
        or embedding["max_response_bytes"] <= 0  # type: ignore[operator]
    ):
        raise ValueError

    rerank = _exact_mapping(
        root["rerank"],
        frozenset({"version"}),
    )
    if (
        not isinstance(rerank["version"], str)
        or not rerank["version"]
    ):
        raise ValueError

    context = _exact_mapping(
        root["context"],
        frozenset(
            {
                "estimator_version",
                "input_budget_ratio_numerator",
                "input_budget_ratio_denominator",
            }
        ),
    )
    if (
        not isinstance(context["estimator_version"], str)
        or not context["estimator_version"]
        or type(context["input_budget_ratio_numerator"])
        is not int
        or type(context["input_budget_ratio_denominator"])
        is not int
        or not 0
        < context["input_budget_ratio_numerator"]  # type: ignore[operator]
        < context["input_budget_ratio_denominator"]  # type: ignore[operator]
    ):
        raise ValueError

    routing = _exact_mapping(
        root["model_routing"],
        frozenset({"route_table_version", "routes"}),
    )
    routes = routing["routes"]
    if (
        routing["route_table_version"] != "model-routes-v1"
        or not isinstance(routes, list)
        or len(routes) != 3
    ):
        raise ValueError
    expected_route_ids = (
        "simple_route",
        "standard_route",
        "complex_route",
    )
    for route, expected_route_id in zip(
        routes,
        expected_route_ids,
        strict=True,
    ):
        route_mapping = _exact_mapping(
            route,
            frozenset({"route_id", "primary", "fallback"}),
        )
        if route_mapping["route_id"] != expected_route_id:
            raise ValueError
        primary = _validate_stage1_target(
            route_mapping["primary"]
        )
        fallback_value = route_mapping["fallback"]
        if fallback_value is None:
            continue
        fallback = _validate_stage1_target(fallback_value)
        if (
            fallback["data_boundary_sha256"]
            != primary["data_boundary_sha256"]
            or fallback["max_input_tokens"]
            != primary["max_input_tokens"]
            or fallback["max_output_tokens"]
            != primary["max_output_tokens"]
            or fallback["output_contract_version"]
            != primary["output_contract_version"]
        ):
            raise ValueError


def stage1_configuration_sha256(
    public_configuration: Mapping[str, object],
) -> str:
    try:
        if (
            not isinstance(public_configuration, Mapping)
            or frozenset(public_configuration)
            != _STAGE1_CONFIGURATION_KEYS
        ):
            raise ValueError
        normalized = _stage1_json_value(public_configuration)
        _validate_stage1_configuration_shape(normalized)
        payload = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (
        TypeError,
        ValueError,
        UnicodeEncodeError,
    ):
        raise ValueError(
            "stage1 configuration is invalid"
        ) from None
    domain = b"stage1-public-configuration-v1"
    return hashlib.sha256(
        len(domain).to_bytes(4, "big")
        + domain
        + len(payload).to_bytes(8, "big")
        + payload
    ).hexdigest()


def build_stage1_public_configuration(
    *,
    embedding_settings: EmbeddingSettings,
    retrieval_runtime: RetrievalRuntime,
    model_routing: ModelRoutingRuntime,
) -> dict[str, object]:
    if (
        not isinstance(embedding_settings, EmbeddingSettings)
        or not isinstance(retrieval_runtime, RetrievalRuntime)
        or not isinstance(model_routing, ModelRoutingRuntime)
        or retrieval_runtime.provider.model_id
        != embedding_settings.model
        or retrieval_runtime.provider.dimension
        != embedding_settings.dimension
        or retrieval_runtime.provider.provider_config_sha256
        != embedding_provider_config_sha256(
            embedding_settings
        )
    ):
        raise ValueError(
            "stage1 runtime configuration is invalid"
        )

    def target_payload(target: object) -> dict[str, object]:
        if target is None:
            raise ValueError(
                "stage1 runtime configuration is invalid"
            )
        return {
            "model_config_sha256": getattr(
                target,
                "model_config_sha256",
            ),
            "max_input_tokens": getattr(
                target,
                "max_input_tokens",
            ),
            "max_output_tokens": getattr(
                target,
                "max_output_tokens",
            ),
            "timeout_seconds": getattr(
                target,
                "timeout_seconds",
            ),
            "data_boundary_sha256": getattr(
                target,
                "data_boundary_sha256",
            ),
            "output_contract_version": getattr(
                target,
                "output_contract_version",
            ),
        }

    configuration: dict[str, object] = {
        "complexity": {
            "policy_version": COMPLEXITY_POLICY_VERSION,
            "probe_top_k": PROBE_SCHEMA_TOP_K,
            "simple_top_k": 5,
            "medium_top_k": 10,
            "complex_top_k": 20,
        },
        "retrieval": {
            "retrieval_version_contract": (
                RETRIEVAL_VERSION_CONTRACT
            ),
            "document_version": SCHEMA_DOCUMENT_VERSION,
            "bm25_version": BM25_VERSION,
            "bm25_k1": BM25_K1,
            "bm25_b": BM25_B,
            "candidate_limit": RETRIEVAL_CANDIDATE_LIMIT,
            "fusion_version": FUSION_VERSION,
            "rrf_k": RRF_K,
            "index_max_entries": INDEX_MAX_ENTRIES,
            "index_embedding_batch_size": (
                INDEX_EMBEDDING_BATCH_SIZE
            ),
            "semantic_version": (
                retrieval_runtime.semantic_version
            ),
        },
        "embedding": {
            "provider_contract": (
                EMBEDDING_PROVIDER_CONTRACT_VERSION
            ),
            "model": embedding_settings.model,
            "dimension": embedding_settings.dimension,
            "endpoint_identity_sha256": (
                embedding_endpoint_identity_sha256(
                    embedding_settings
                )
            ),
            "timeout_seconds": (
                embedding_settings.timeout_seconds
            ),
            "max_batch_documents": (
                embedding_settings.max_batch_documents
            ),
            "max_response_bytes": (
                embedding_settings.max_response_bytes
            ),
        },
        "rerank": {"version": RERANK_VERSION},
        "context": {
            "estimator_version": CONTEXT_ESTIMATOR_VERSION,
            "input_budget_ratio_numerator": (
                CONTEXT_INPUT_BUDGET_NUMERATOR
            ),
            "input_budget_ratio_denominator": (
                CONTEXT_INPUT_BUDGET_DENOMINATOR
            ),
        },
        "model_routing": {
            "route_table_version": (
                model_routing.route_table.version
            ),
            "routes": [
                {
                    "route_id": route.route_id,
                    "primary": target_payload(route.primary),
                    "fallback": (
                        target_payload(route.fallback)
                        if route.fallback is not None
                        else None
                    ),
                }
                for route in model_routing.route_table.routes
            ],
        },
    }
    try:
        normalized = _stage1_json_value(configuration)
        _validate_stage1_configuration_shape(normalized)
    except (TypeError, ValueError):
        raise ValueError(
            "stage1 runtime configuration is invalid"
        ) from None
    return configuration


class Stage1SelectedConfiguration(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    contract_version: str = (
        "stage1-selected-configuration-v1"
    )
    public_configuration: dict[str, object]
    stage1_config_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )

    @model_validator(mode="after")
    def validate_selected_configuration(self) -> Self:
        if (
            self.contract_version
            != "stage1-selected-configuration-v1"
            or self.stage1_config_sha256
            != stage1_configuration_sha256(
                self.public_configuration
            )
        ):
            raise ValueError(
                "stage1 selected configuration is invalid"
            )
        return self


def build_stage1_selected_configuration(
    public_configuration: Mapping[str, object],
) -> Stage1SelectedConfiguration:
    try:
        normalized = _stage1_json_value(
            public_configuration
        )
        if not isinstance(normalized, dict):
            raise ValueError
        digest = stage1_configuration_sha256(normalized)
        return Stage1SelectedConfiguration(
            public_configuration=normalized,
            stage1_config_sha256=digest,
        )
    except (TypeError, ValueError):
        raise ValueError(
            "stage1 selected configuration is invalid"
        ) from None


def load_stage1_selected_configuration(
    path: Path,
) -> Stage1SelectedConfiguration:
    try:
        return Stage1SelectedConfiguration.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (
        OSError,
        UnicodeDecodeError,
        ValidationError,
        ValueError,
    ):
        raise ValueError(
            "stage1 selected configuration is invalid"
        ) from None


def _stage1_calibration_baseline_id(
    payload: Mapping[str, object],
) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise ValueError(
            "stage1 calibration freeze is invalid"
        ) from None
    domain = b"stage1-calibration-freeze-v1"
    return hashlib.sha256(
        len(domain).to_bytes(4, "big")
        + domain
        + len(encoded).to_bytes(8, "big")
        + encoded
    ).hexdigest()


class Stage1CalibrationFreeze(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    contract_version: str = "stage1-calibration-freeze-v1"
    development_file_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    development_normalized_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    calibration_file_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    calibration_normalized_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    stage1_config_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    controlled_code_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    stage1_calibration_baseline_id: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )

    @model_validator(mode="after")
    def validate_freeze(self) -> Self:
        payload = self.model_dump(
            mode="json",
            exclude={"stage1_calibration_baseline_id"},
        )
        if (
            self.contract_version
            != "stage1-calibration-freeze-v1"
            or self.stage1_calibration_baseline_id
            != _stage1_calibration_baseline_id(payload)
        ):
            raise ValueError(
                "stage1 calibration freeze is invalid"
            )
        return self


def load_stage1_calibration_freeze(
    path: Path,
) -> Stage1CalibrationFreeze:
    try:
        return Stage1CalibrationFreeze.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (
        OSError,
        UnicodeDecodeError,
        ValidationError,
        ValueError,
    ):
        raise ValueError(
            "stage1 calibration freeze is invalid"
        ) from None


def build_stage1_calibration_freeze(
    *,
    development_file_sha256: str,
    development_normalized_sha256: str,
    calibration_file_sha256: str,
    calibration_normalized_sha256: str,
    public_configuration: Mapping[str, object],
    controlled_code_sha256_value: str,
) -> Stage1CalibrationFreeze:
    payload = {
        "contract_version": "stage1-calibration-freeze-v1",
        "development_file_sha256": development_file_sha256,
        "development_normalized_sha256": (
            development_normalized_sha256
        ),
        "calibration_file_sha256": calibration_file_sha256,
        "calibration_normalized_sha256": (
            calibration_normalized_sha256
        ),
        "stage1_config_sha256": stage1_configuration_sha256(
            public_configuration
        ),
        "controlled_code_sha256": (
            controlled_code_sha256_value
        ),
    }
    return Stage1CalibrationFreeze(
        **payload,
        stage1_calibration_baseline_id=(
            _stage1_calibration_baseline_id(payload)
        ),
    )


def verify_stage1_calibration_freeze(
    freeze: Stage1CalibrationFreeze,
    *,
    development_file_sha256: str,
    development_normalized_sha256: str,
    calibration_file_sha256: str,
    calibration_normalized_sha256: str,
    public_configuration: Mapping[str, object],
    controlled_code_sha256_value: str,
) -> None:
    try:
        expected = build_stage1_calibration_freeze(
            development_file_sha256=development_file_sha256,
            development_normalized_sha256=(
                development_normalized_sha256
            ),
            calibration_file_sha256=calibration_file_sha256,
            calibration_normalized_sha256=(
                calibration_normalized_sha256
            ),
            public_configuration=public_configuration,
            controlled_code_sha256_value=(
                controlled_code_sha256_value
            ),
        )
    except ValueError:
        raise ValueError(
            "stage1 calibration freeze is invalid"
        ) from None
    if not isinstance(freeze, Stage1CalibrationFreeze) or freeze != expected:
        raise ValueError(
            "stage1 calibration freeze is invalid"
        )
