from pathlib import Path

import pytest

from app.config import DatabaseSettings, LLMSettings
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
