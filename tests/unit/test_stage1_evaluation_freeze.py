from pathlib import Path

import pytest

from app.config import (
    EmbeddingSettings,
    LLMRouteSettings,
    LLMSettings,
)
from app.generation import build_configured_model_routing_runtime
from app.schema_linking import (
    EmbeddingIndexRegistry,
    OpenAICompatibleEmbeddingProvider,
    RetrievalRuntime,
)
from evaluation.code_freeze import (
    Stage1CalibrationFreeze,
    build_stage1_calibration_freeze,
    build_stage1_public_configuration,
    build_stage1_selected_configuration,
    load_stage1_calibration_freeze,
    load_stage1_selected_configuration,
    stage1_configuration_sha256,
    verify_stage1_calibration_freeze,
)


class _UnusedLLMProvider:
    def generate(self, messages, *, timeout_seconds=None):
        raise AssertionError("provider must not be called")


def _runtime_configuration():
    embedding_settings = EmbeddingSettings(
        base_url="https://embedding.example.test/v1",
        api_key="embedding-runtime-test-secret",
        model="text-embedding-v4",
        dimension=1024,
    )
    retrieval_runtime = RetrievalRuntime(
        provider=OpenAICompatibleEmbeddingProvider(
            embedding_settings
        ),
        registry=EmbeddingIndexRegistry(),
        semantic_version="semantic-v1",
    )
    simple = LLMSettings(
        base_url="https://models.example.test/v1",
        api_key="model-runtime-test-secret",
        model="simple-model",
    )
    standard = LLMSettings(
        base_url="https://models.example.test/v1",
        api_key="model-runtime-test-secret",
        model="standard-model",
    )
    complex_settings = LLMSettings(
        base_url="https://models.example.test/v1",
        api_key="model-runtime-test-secret",
        model="complex-model",
    )
    route_settings = LLMRouteSettings(
        simple=simple,
        standard=standard,
        complex=complex_settings,
        data_boundary_id="stage1-test-boundary-v1",
    )
    model_routing = build_configured_model_routing_runtime(
        settings=route_settings,
        providers={
            "simple": _UnusedLLMProvider(),
            "standard": _UnusedLLMProvider(),
            "complex": _UnusedLLMProvider(),
        },
    )
    return embedding_settings, retrieval_runtime, model_routing


def test_public_configuration_is_derived_from_runtime_without_secrets() -> None:
    (
        embedding_settings,
        retrieval_runtime,
        model_routing,
    ) = _runtime_configuration()

    configuration = build_stage1_public_configuration(
        embedding_settings=embedding_settings,
        retrieval_runtime=retrieval_runtime,
        model_routing=model_routing,
    )
    serialized = str(configuration)

    assert configuration["rerank"] == {
        "version": "schema-rerank-v2"
    }
    assert configuration["embedding"]["model"] == (  # type: ignore[index]
        "text-embedding-v4"
    )
    assert configuration["embedding"]["dimension"] == 1024  # type: ignore[index]
    assert "embedding-runtime-test-secret" not in serialized
    assert "model-runtime-test-secret" not in serialized
    assert len(stage1_configuration_sha256(configuration)) == 64

    mismatched_settings = EmbeddingSettings(
        base_url="https://other-embedding.example.test/v1",
        api_key="different-runtime-test-secret",
        model="text-embedding-v4",
        dimension=1024,
    )
    with pytest.raises(
        ValueError,
        match=r"^stage1 runtime configuration is invalid$",
    ):
        build_stage1_public_configuration(
            embedding_settings=mismatched_settings,
            retrieval_runtime=retrieval_runtime,
            model_routing=model_routing,
        )


def _configuration() -> dict[str, object]:
    return {
        "complexity": {
            "policy_version": "complexity-v1",
            "probe_top_k": 20,
            "simple_top_k": 5,
            "medium_top_k": 10,
            "complex_top_k": 20,
        },
        "retrieval": {
            "retrieval_version_contract": "retrieval-version-v1",
            "document_version": "schema-doc-v1",
            "bm25_version": "bm25-v1",
            "bm25_k1": 1.5,
            "bm25_b": 0.75,
            "candidate_limit": 20,
            "fusion_version": "rrf-v1",
            "rrf_k": 60,
            "index_max_entries": 32,
            "index_embedding_batch_size": 10,
            "semantic_version": "semantic-v1",
        },
        "embedding": {
            "provider_contract": "openai-compatible-embedding-v1",
            "model": "text-embedding-v4",
            "dimension": 1024,
            "endpoint_identity_sha256": "1" * 64,
            "timeout_seconds": 10,
            "max_batch_documents": 10,
            "max_response_bytes": 4_194_304,
        },
        "rerank": {
            "version": "schema-rerank-v2",
        },
        "context": {
            "estimator_version": "utf8-bytes-div-3-v1",
            "input_budget_ratio_numerator": 4,
            "input_budget_ratio_denominator": 5,
        },
        "model_routing": {
            "route_table_version": "model-routes-v1",
            "routes": [
                {
                    "route_id": "simple_route",
                    "primary": {
                        "model_config_sha256": "a" * 64,
                        "max_input_tokens": 32768,
                        "max_output_tokens": 2048,
                        "timeout_seconds": 30,
                        "data_boundary_sha256": "b" * 64,
                        "output_contract_version": (
                            "openai-compatible-json-v1"
                        ),
                    },
                    "fallback": None,
                },
                {
                    "route_id": "standard_route",
                    "primary": {
                        "model_config_sha256": "c" * 64,
                        "max_input_tokens": 32768,
                        "max_output_tokens": 2048,
                        "timeout_seconds": 30,
                        "data_boundary_sha256": "b" * 64,
                        "output_contract_version": (
                            "openai-compatible-json-v1"
                        ),
                    },
                    "fallback": None,
                },
                {
                    "route_id": "complex_route",
                    "primary": {
                        "model_config_sha256": "d" * 64,
                        "max_input_tokens": 32768,
                        "max_output_tokens": 2048,
                        "timeout_seconds": 30,
                        "data_boundary_sha256": "b" * 64,
                        "output_contract_version": (
                            "openai-compatible-json-v1"
                        ),
                    },
                    "fallback": None,
                },
            ],
        },
    }


def _freeze():
    return build_stage1_calibration_freeze(
        development_file_sha256="1" * 64,
        development_normalized_sha256="2" * 64,
        calibration_file_sha256="3" * 64,
        calibration_normalized_sha256="4" * 64,
        public_configuration=_configuration(),
        controlled_code_sha256_value="5" * 64,
    )


def test_stage1_configuration_hash_is_stable_and_secret_free() -> None:
    first = _configuration()
    second = dict(reversed(tuple(first.items())))

    assert stage1_configuration_sha256(first) == (
        stage1_configuration_sha256(second)
    )
    assert len(stage1_configuration_sha256(first)) == 64

    first["embedding"] = {
        **first["embedding"],  # type: ignore[arg-type]
        "api_key": "must-not-enter-freeze",
    }
    with pytest.raises(
        ValueError,
        match=r"^stage1 configuration is invalid$",
    ):
        stage1_configuration_sha256(first)


def test_stage1_selected_configuration_and_freeze_round_trip(
    tmp_path: Path,
) -> None:
    selected = build_stage1_selected_configuration(
        _configuration()
    )
    selected_path = tmp_path / "selected.json"
    selected_path.write_text(
        selected.model_dump_json(),
        encoding="utf-8",
    )
    freeze = _freeze()
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(
        freeze.model_dump_json(),
        encoding="utf-8",
    )

    assert (
        load_stage1_selected_configuration(selected_path)
        == selected
    )
    assert load_stage1_calibration_freeze(freeze_path) == freeze


def test_stage1_configuration_requires_complete_selected_behavior() -> None:
    configuration = _configuration()
    retrieval = dict(configuration["retrieval"])  # type: ignore[arg-type]
    retrieval.pop("rrf_k")
    configuration["retrieval"] = retrieval

    with pytest.raises(
        ValueError,
        match=r"^stage1 configuration is invalid$",
    ):
        stage1_configuration_sha256(configuration)


@pytest.mark.parametrize(
    "mutation",
    (
        {"development_file_sha256": "6" * 64},
        {"development_normalized_sha256": "6" * 64},
        {"calibration_file_sha256": "6" * 64},
        {"calibration_normalized_sha256": "6" * 64},
        {"controlled_code_sha256_value": "6" * 64},
    ),
)
def test_stage1_freeze_rejects_any_evidence_drift(
    mutation: dict[str, str],
) -> None:
    freeze = _freeze()
    arguments = {
        "development_file_sha256": "1" * 64,
        "development_normalized_sha256": "2" * 64,
        "calibration_file_sha256": "3" * 64,
        "calibration_normalized_sha256": "4" * 64,
        "public_configuration": _configuration(),
        "controlled_code_sha256_value": "5" * 64,
    }
    arguments.update(mutation)

    with pytest.raises(
        ValueError,
        match=r"^stage1 calibration freeze is invalid$",
    ):
        verify_stage1_calibration_freeze(
            freeze,
            **arguments,
        )


def test_stage1_freeze_rejects_configuration_drift() -> None:
    freeze = _freeze()
    changed = _configuration()
    changed["retrieval"] = {
        **changed["retrieval"],  # type: ignore[arg-type]
        "rrf_k": 61,
    }

    with pytest.raises(
        ValueError,
        match=r"^stage1 calibration freeze is invalid$",
    ):
        verify_stage1_calibration_freeze(
            freeze,
            development_file_sha256="1" * 64,
            development_normalized_sha256="2" * 64,
            calibration_file_sha256="3" * 64,
            calibration_normalized_sha256="4" * 64,
            public_configuration=changed,
            controlled_code_sha256_value="5" * 64,
        )


def test_stage1_freeze_id_is_self_validating() -> None:
    freeze = _freeze()

    assert (
        build_stage1_calibration_freeze(
            development_file_sha256="1" * 64,
            development_normalized_sha256="2" * 64,
            calibration_file_sha256="3" * 64,
            calibration_normalized_sha256="4" * 64,
            public_configuration=_configuration(),
            controlled_code_sha256_value="5" * 64,
        )
        == freeze
    )
    with pytest.raises(ValueError):
        Stage1CalibrationFreeze.model_validate(
            {
                **freeze.model_dump(),
                "stage1_calibration_baseline_id": "0" * 64,
            }
        )
