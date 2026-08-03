from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY

import pytest

from app.config import (
    DatabaseSettings,
    EmbeddingSettings,
    LLMRouteSettings,
    LLMSettings,
)
from evaluation import (
    AuditStatus,
    CaseEvaluation,
    CaseStatus,
    ComparisonResult,
    ExpectedBehavior,
)
from app.workflow import FinalStatus
from evaluation.runner import case_evidence_sha256


def _passing_evaluation() -> CaseEvaluation:
    fields: dict[str, object] = {
        "case_id": "PG-MVP-001",
        "evaluation_baseline_id": "0" * 64,
        "initial_status": CaseStatus.DRAFT,
        "expected_behavior": ExpectedBehavior.EXECUTE,
        "expected_final_status": FinalStatus.SUCCEEDED_FIRST_PASS,
        "actual_final_status": FinalStatus.SUCCEEDED_FIRST_PASS,
        "gold_validation_passed": True,
        "gold_executed": True,
        "prediction_validation_passed": True,
        "prediction_execute_count": 1,
        "comparison": ComparisonResult(
            passed=True,
            code="RESULT_MATCH",
            message="results match",
            predicted_row_count=1,
            gold_row_count=1,
        ),
        "table_recall_passed": True,
        "field_recall_passed": True,
        "attempt_count": 1,
        "trace_sha256": "a" * 64,
        "passed": True,
        "code": "EVALUATION_PASS",
    }
    return CaseEvaluation(
        **fields,
        evidence_sha256=case_evidence_sha256(fields),
        audit_status=AuditStatus.PENDING,
    )


def test_model_config_hash_excludes_api_key_but_includes_prompt_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import run_pagila_evaluation

    first = LLMSettings(
        base_url="https://model.example/v1",
        api_key="first-secret",
        model="test-model",
    )
    second = LLMSettings(
        base_url="https://model.example/v1",
        api_key="second-secret",
        model="test-model",
    )

    anchors = {
        "semantic_manifest_sha256": "1" * 64,
        "controlled_code_sha256": "2" * 64,
    }
    original = run_pagila_evaluation.model_config_hash(
        first,
        **anchors,
    )
    assert original == run_pagila_evaluation.model_config_hash(
        second,
        **anchors,
    )
    assert original != run_pagila_evaluation.model_config_hash(
        first,
        **{
            **anchors,
            "semantic_manifest_sha256": "3" * 64,
        },
    )
    assert original != run_pagila_evaluation.model_config_hash(
        first,
        **{
            **anchors,
            "controlled_code_sha256": "4" * 64,
        },
    )

    monkeypatch.setattr(
        run_pagila_evaluation,
        "PROMPT_VERSION",
        "different-contract",
    )
    assert original != run_pagila_evaluation.model_config_hash(
        first,
        **anchors,
    )


def test_stage1_evaluation_requires_embedding_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import run_pagila_evaluation

    def missing_settings(env_file: Path) -> EmbeddingSettings:
        assert env_file == Path("settings.env")
        return EmbeddingSettings.model_validate({})

    monkeypatch.setattr(
        run_pagila_evaluation,
        "load_embedding_settings",
        missing_settings,
        raising=False,
    )

    with pytest.raises(
        ValueError,
        match=r"^embedding settings are required$",
    ):
        run_pagila_evaluation._load_required_embedding_settings(
            Path("settings.env")
        )


def test_partial_embedding_configuration_fails_with_public_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import run_pagila_evaluation

    def partial_settings(env_file: Path) -> EmbeddingSettings:
        assert env_file == Path("settings.env")
        return EmbeddingSettings.model_validate(
                {
                    "base_url": "https://embedding.invalid/v1",
                    "model": "embedding-stub",
                }
        )

    monkeypatch.setattr(
        run_pagila_evaluation,
        "load_embedding_settings",
        partial_settings,
        raising=False,
    )

    with pytest.raises(
        ValueError,
        match=r"^embedding settings are invalid$",
    ):
        run_pagila_evaluation._load_optional_embedding_settings(
            Path("settings.env")
        )


def test_evaluate_assembles_routes_and_injects_hybrid_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from tools import run_pagila_evaluation

    def llm(model: str) -> LLMSettings:
        return LLMSettings(
            base_url="https://llm.invalid/v1",
            api_key="unit-test-credential",
            model=model,
        )

    route_settings = LLMRouteSettings(
        simple=llm("simple-stub"),
        standard=llm("standard-stub"),
        complex=llm("complex-stub"),
        fallback=llm("fallback-stub"),
        fallback_route_ids=("complex_route",),
        data_boundary_id="evaluation-boundary-v1",
    )
    case = SimpleNamespace(status=CaseStatus.DRAFT)
    suite = SimpleNamespace(
        cases=(case,),
        file_sha256="1" * 64,
        status_neutral_sha256="2" * 64,
    )
    baseline = SimpleNamespace(
        gold_cases=SimpleNamespace(
            initial_file_sha256=suite.file_sha256,
            status_neutral_sha256=suite.status_neutral_sha256,
        ),
        semantic=SimpleNamespace(
            manifest_sha256=(
                run_pagila_evaluation
                .VIEW_SEMANTIC_MANIFEST_SHA256
            ),
            database_schema_sha256=(
                run_pagila_evaluation
                .PAGILA_DATABASE_SCHEMA_SHA256
            ),
        ),
        software=SimpleNamespace(
            controlled_code_sha256="3" * 64,
        ),
        evaluation_baseline_id="4" * 64,
    )
    manifest = SimpleNamespace(
        enriched_schema_version="enriched-semantic-v1"
    )
    semantic_connector = object()
    route_runtime = object()
    embedding_settings = object()
    embedding_provider = object()
    embedding_registry = object()
    retrieval_runtime = object()
    public_configuration = {"stage1": "public"}
    evaluation = object()
    report = object()
    calls: dict[str, list[object]] = {
        "route_loader": [],
        "llm_provider": [],
        "route_builder": [],
        "embedding_loader": [],
        "embedding_provider": [],
        "embedding_registry": [],
        "retrieval_runtime": [],
        "public_configuration": [],
        "evaluate_case": [],
    }

    class Connector:
        def open(self) -> None:
            return None

        def close(self) -> None:
            return None

        def read_metadata(self, *args: object) -> object:
            del args
            return object()

    monkeypatch.setattr(
        run_pagila_evaluation,
        "load_case_suite",
        lambda path: suite,
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "load_baseline",
        lambda path: baseline,
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "verify_static_evaluation_freeze",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "verify_evaluation_environment",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "load_database_settings",
        lambda path: DatabaseSettings(
            dsn=(
                "postgresql://text_to_sql_reader:"
                "unit-test@127.0.0.1:55432/pagila"
            )
        ),
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "verify_database_execution_freeze",
        lambda *args: None,
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "verify_database_target",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "PostgreSQLConnector",
        lambda settings: Connector(),
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "load_view_semantic_manifest",
        lambda *args, **kwargs: manifest,
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "FrozenSemanticConnector",
        lambda connector, loaded_manifest: (
            semantic_connector
        ),
    )
    def load_routes(path: Path) -> LLMRouteSettings:
        calls["route_loader"].append(path)
        return route_settings

    monkeypatch.setattr(
        run_pagila_evaluation,
        "load_llm_route_settings",
        load_routes,
        raising=False,
    )

    def build_llm_provider(settings: LLMSettings) -> object:
        calls["llm_provider"].append(settings)
        return SimpleNamespace(generate=lambda *args, **kwargs: None)

    monkeypatch.setattr(
        run_pagila_evaluation,
        "OpenAICompatibleLLMProvider",
        build_llm_provider,
    )

    def build_routes(*, settings, providers) -> object:
        calls["route_builder"].append((settings, providers))
        return route_runtime

    monkeypatch.setattr(
        run_pagila_evaluation,
        "build_configured_model_routing_runtime",
        build_routes,
        raising=False,
    )

    def load_embedding(path: Path) -> object:
        calls["embedding_loader"].append(path)
        return embedding_settings

    monkeypatch.setattr(
        run_pagila_evaluation,
        "load_embedding_settings",
        load_embedding,
        raising=False,
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "OpenAICompatibleEmbeddingProvider",
        lambda settings: (
            calls["embedding_provider"].append(settings)
            or embedding_provider
        ),
        raising=False,
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "EmbeddingIndexRegistry",
        lambda: (
            calls["embedding_registry"].append(object())
            or embedding_registry
        ),
        raising=False,
    )

    def build_retrieval_runtime(**kwargs: object) -> object:
        calls["retrieval_runtime"].append(kwargs)
        return retrieval_runtime

    monkeypatch.setattr(
        run_pagila_evaluation,
        "RetrievalRuntime",
        build_retrieval_runtime,
        raising=False,
    )

    def build_public_configuration(**kwargs: object) -> object:
        calls["public_configuration"].append(kwargs)
        return public_configuration

    monkeypatch.setattr(
        run_pagila_evaluation,
        "build_stage1_public_configuration",
        build_public_configuration,
        raising=False,
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "_verify_stage1_runtime_freeze",
        lambda configuration: (
            "5" * 64
            if configuration is public_configuration
            else (_ for _ in ()).throw(AssertionError)
        ),
    )

    def evaluate(current_case: object, **kwargs: object) -> object:
        calls["evaluate_case"].append((current_case, kwargs))
        return evaluation

    monkeypatch.setattr(
        run_pagila_evaluation,
        "evaluate_case",
        evaluate,
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "build_evaluation_report",
        lambda *args, **kwargs: report,
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "write_report_atomic",
        lambda path, built_report: None,
    )

    actual = run_pagila_evaluation.evaluate_to_report(
        cases_path=tmp_path / "cases.jsonl",
        baseline_path=tmp_path / "baseline.json",
        report_path=tmp_path / "report.json",
        env_file=tmp_path / "settings.env",
    )

    assert actual is report
    assert calls["route_loader"] == [tmp_path / "settings.env"]
    assert calls["llm_provider"] == [
        route_settings.simple,
        route_settings.standard,
        route_settings.complex,
        route_settings.fallback,
    ]
    assert len(calls["route_builder"]) == 1
    built_settings, providers = calls["route_builder"][0]
    assert built_settings is route_settings
    assert tuple(providers) == (
        "simple",
        "standard",
        "complex",
        "fallback",
    )
    assert calls["embedding_loader"] == [
        tmp_path / "settings.env"
    ]
    assert calls["embedding_provider"] == [embedding_settings]
    assert len(calls["embedding_registry"]) == 1
    assert calls["retrieval_runtime"] == [
        {
            "provider": embedding_provider,
            "registry": embedding_registry,
            "semantic_version": manifest.enriched_schema_version,
        }
    ]
    assert calls["public_configuration"] == [
        {
            "embedding_settings": embedding_settings,
            "retrieval_runtime": retrieval_runtime,
            "model_routing": route_runtime,
        }
    ]
    assert calls["evaluate_case"] == [
        (
            case,
            {
                "evaluation_baseline_id": (
                    baseline.evaluation_baseline_id
                ),
                "connector": semantic_connector,
                "model_routing": route_runtime,
                "retrieval_runtime": retrieval_runtime,
                "trace_sink": ANY,
            },
        )
    ]


def test_database_target_must_match_locked_container_port_and_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import run_pagila_evaluation

    monkeypatch.setattr(
        run_pagila_evaluation,
        "_docker_output",
        lambda container_name, arguments: (
            b"0.0.0.0:55432\n[::]:55432\n"
        ),
    )
    settings = DatabaseSettings(
        dsn=(
            "postgresql://text_to_sql_reader:secret"
            "@127.0.0.1:55432/pagila"
        )
    )

    run_pagila_evaluation.verify_database_target(
        settings,
        container_name="text-to-sql-pagila-postgres",
    )


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://text_to_sql_reader:secret@db.example:55432/pagila",
        "postgresql://text_to_sql_reader:secret@127.0.0.1:5432/pagila",
        "postgresql://postgres:secret@127.0.0.1:55432/pagila",
    ],
)
def test_database_target_rejects_unbound_or_privileged_dsn(
    monkeypatch: pytest.MonkeyPatch,
    dsn: str,
) -> None:
    from tools import run_pagila_evaluation

    monkeypatch.setattr(
        run_pagila_evaluation,
        "_docker_output",
        lambda container_name, arguments: b"0.0.0.0:55432\n",
    )

    with pytest.raises(
        ValueError,
        match=r"^evaluation database target does not match$",
    ):
        run_pagila_evaluation.verify_database_target(
            DatabaseSettings(dsn=dsn),
            container_name="text-to-sql-pagila-postgres",
        )


def test_evaluate_command_prints_only_case_id_and_stable_code(
    monkeypatch,
    capsys,
) -> None:
    from tools import run_pagila_evaluation

    evaluation = _passing_evaluation()

    class _Report:
        evaluations = (evaluation,)

    monkeypatch.setattr(
        run_pagila_evaluation,
        "evaluate_to_report",
        lambda **kwargs: _Report(),
    )

    exit_code = run_pagila_evaluation.run(
        [
            "evaluate",
            "--cases",
            "cases.jsonl",
            "--baseline",
            "baseline.json",
            "--report",
            "report.json",
            "--env-file",
            ".env",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out == (
        "PG-MVP-001 EVALUATION_PASS pending\n"
    )


def test_review_and_verify_commands_delegate_one_exact_case(
    monkeypatch,
) -> None:
    from tools import run_pagila_evaluation

    current_baseline = object()
    calls: list[tuple[str, Path, object, str]] = []
    monkeypatch.setattr(
        run_pagila_evaluation,
        "_load_current_audit_baseline",
        lambda path: (
            current_baseline
            if path == Path("baseline.json")
            else (_ for _ in ()).throw(AssertionError)
        ),
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "review_case",
        lambda report_path, *, current_baseline, case_id, approved: calls.append(
            (
                "approve" if approved else "reject",
                report_path,
                current_baseline,
                case_id,
            )
        ),
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "verify_case",
        lambda cases_path, report_path, *, current_baseline, case_id: calls.append(
            ("verify", cases_path, current_baseline, case_id)
        ),
    )

    assert (
        run_pagila_evaluation.run(
            [
                "review-case",
                "--report",
                "report.json",
                "--baseline",
                "baseline.json",
                "--case-id",
                "PG-MVP-001",
                "--approve",
            ]
        )
        == 0
    )
    assert (
        run_pagila_evaluation.run(
            [
                "verify-case",
                "--cases",
                "cases.jsonl",
                "--report",
                "report.json",
                "--baseline",
                "baseline.json",
                "--case-id",
                "PG-MVP-001",
            ]
        )
        == 0
    )
    assert calls == [
        (
            "approve",
            Path("report.json"),
            current_baseline,
            "PG-MVP-001",
        ),
        (
            "verify",
            Path("cases.jsonl"),
            current_baseline,
            "PG-MVP-001",
        ),
    ]


def test_freeze_baseline_command_delegates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from tools import run_pagila_evaluation

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        run_pagila_evaluation,
        "freeze_baseline",
        lambda **kwargs: calls.append(kwargs),
        raising=False,
    )
    source = tmp_path / "source.json"
    output = tmp_path / "baseline.json"

    assert (
        run_pagila_evaluation.run(
            [
                "freeze-baseline",
                "--baseline",
                str(source),
                "--output",
                str(output),
                "--cases",
                "cases.jsonl",
                "--env-file",
                ".env",
            ]
        )
        == 0
    )
    assert calls == [
        {
            "source_baseline_path": source,
            "output_path": output,
            "cases_path": Path("cases.jsonl"),
            "env_file": Path(".env"),
            "pagila_container": (
                "text-to-sql-pagila-postgres"
            ),
        }
    ]


def test_verified_status_requires_approved_case_evidence() -> None:
    from tools import run_pagila_evaluation

    class _Report:
        evaluations = (_passing_evaluation(),)

    with pytest.raises(ValueError, match="approved evidence"):
        run_pagila_evaluation._require_verified_evidence(
            _Report(),
            {"PG-MVP-001"},
        )
