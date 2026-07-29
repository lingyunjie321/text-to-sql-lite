import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import DatabaseSettings
from evaluation.loader import load_case_suite
from evaluation.report import load_baseline, load_report
from tools import run_pagila_evaluation


def test_docker_probe_failure_does_not_expose_stderr_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_run(*args: object, **kwargs: object):
        del args, kwargs
        return subprocess.CompletedProcess(
            args=("docker",),
            returncode=1,
            stdout=b"",
            stderr=b"postgresql://reader:secret@db/pagila",
        )

    monkeypatch.setattr(
        run_pagila_evaluation.subprocess,
        "run",
        failed_run,
    )

    with pytest.raises(ValueError) as captured:
        run_pagila_evaluation.collect_runtime_observation(
            "text-to-sql-pagila-postgres"
        )

    assert "secret" not in str(captured.value)
    assert "postgresql://" not in str(captured.value)


def test_docker_probe_rejects_invalid_output_without_codec_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run_pagila_evaluation.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=("docker",),
            returncode=0,
            stdout=b"\xff",
            stderr=b"",
        ),
    )

    with pytest.raises(
        ValueError,
        match=r"^evaluation runtime probe failed$",
    ):
        run_pagila_evaluation.collect_runtime_observation(
            "text-to-sql-pagila-postgres"
        )


@pytest.mark.parametrize(
    ("loader", "message"),
    [
        (load_baseline, "evaluation baseline is invalid"),
        (load_report, "evaluation report is invalid"),
    ],
)
def test_invalid_utf8_artifacts_fail_with_public_safe_errors(
    tmp_path: Path,
    loader,
    message: str,
) -> None:
    path = tmp_path / "artifact.json"
    path.write_bytes(b"\xffprivate")

    with pytest.raises(ValueError, match=f"^{message}$"):
        loader(path)


def test_evaluate_refuses_baseline_drift_before_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential_loads = 0

    def reject_baseline(**kwargs: object) -> None:
        del kwargs
        raise ValueError("evaluation baseline does not match")

    def credential_loader(*args: object, **kwargs: object):
        nonlocal credential_loads
        del args, kwargs
        credential_loads += 1
        raise AssertionError

    monkeypatch.setattr(
        run_pagila_evaluation,
        "verify_evaluation_environment",
        reject_baseline,
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "load_database_settings",
        credential_loader,
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "load_llm_settings",
        credential_loader,
    )

    with pytest.raises(ValueError, match="baseline"):
        run_pagila_evaluation.evaluate_to_report(
            cases_path=Path("evaluation/cases/pagila_mvp.jsonl"),
            baseline_path=Path("evaluation/pagila_baseline.json"),
            report_path=Path("unused.json"),
            env_file=Path(".env"),
        )

    assert credential_loads == 0


def test_evaluate_requires_exact_all_draft_gold_before_probes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Path("evaluation/cases/pagila_mvp.jsonl").read_bytes()
    changed = source.replace(
        b'"status":"draft"',
        b'"status":"verified"',
        1,
    )
    if changed == source:
        changed = source.replace(
            b'"status": "draft"',
            b'"status": "verified"',
            1,
        )
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_bytes(changed)
    original_suite = load_case_suite(
        Path("evaluation/cases/pagila_mvp.jsonl")
    )
    probes = 0

    def forbidden_probe(**kwargs: object) -> None:
        nonlocal probes
        del kwargs
        probes += 1
        raise AssertionError("runtime probed too early")

    monkeypatch.setattr(
        run_pagila_evaluation,
        "verify_evaluation_environment",
        forbidden_probe,
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "load_baseline",
        lambda path: SimpleNamespace(
            gold_cases=SimpleNamespace(
                initial_file_sha256=original_suite.file_sha256,
                status_neutral_sha256=(
                    original_suite.status_neutral_sha256
                ),
            )
        ),
    )

    with pytest.raises(ValueError, match="all draft"):
        run_pagila_evaluation.evaluate_to_report(
            cases_path=cases_path,
            baseline_path=Path("evaluation/pagila_baseline.json"),
            report_path=tmp_path / "report.json",
            env_file=Path(".env"),
        )

    assert probes == 0


def test_evaluate_refuses_unbound_database_before_llm_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm_credential_loads = 0

    monkeypatch.setattr(
        run_pagila_evaluation,
        "verify_evaluation_environment",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "load_database_settings",
        lambda env_file: DatabaseSettings(
            dsn=(
                "postgresql://text_to_sql_reader:secret"
                "@127.0.0.1:55432/pagila"
            )
        ),
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "verify_database_target",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("evaluation database target does not match")
        ),
    )

    def load_llm(*args: object, **kwargs: object) -> None:
        nonlocal llm_credential_loads
        del args, kwargs
        llm_credential_loads += 1

    monkeypatch.setattr(
        run_pagila_evaluation,
        "load_llm_settings",
        load_llm,
    )

    with pytest.raises(ValueError, match="database target"):
        run_pagila_evaluation.evaluate_to_report(
            cases_path=Path("evaluation/cases/pagila_mvp.jsonl"),
            baseline_path=Path("evaluation/pagila_baseline.json"),
            report_path=Path("unused.json"),
            env_file=Path(".env"),
        )

    assert llm_credential_loads == 0


@pytest.mark.parametrize(
    ("command", "arguments"),
    [
        (
            "review",
            [
                "review-case",
                "--report",
                "report.json",
                "--baseline",
                "baseline.json",
                "--case-id",
                "PG-MVP-001",
                "--approve",
            ],
        ),
        (
            "verify",
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
            ],
        ),
    ],
)
def test_audit_commands_reject_stale_static_freeze_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    arguments: list[str],
) -> None:
    mutations: list[str] = []
    monkeypatch.setattr(
        run_pagila_evaluation,
        "_load_current_audit_baseline",
        lambda path: (_ for _ in ()).throw(
            ValueError("evaluation freeze does not match")
        ),
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "review_case",
        lambda *args, **kwargs: mutations.append("review"),
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "verify_case",
        lambda *args, **kwargs: mutations.append("verify"),
    )

    with pytest.raises(ValueError, match="freeze"):
        run_pagila_evaluation.run(arguments)

    assert mutations == [], command


def test_database_execution_drift_fails_before_connector_or_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {
        "target": 0,
        "connector": 0,
        "llm": 0,
        "provider": 0,
    }
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
        lambda env_file: DatabaseSettings(
            dsn=(
                "postgresql://text_to_sql_reader:secret"
                "@127.0.0.1:55432/pagila"
            ),
            max_result_rows=999,
        ),
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "verify_database_target",
        lambda *args, **kwargs: calls.__setitem__(
            "target", calls["target"] + 1
        ),
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "PostgreSQLConnector",
        lambda *args, **kwargs: calls.__setitem__(
            "connector", calls["connector"] + 1
        ),
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "load_llm_settings",
        lambda *args, **kwargs: calls.__setitem__(
            "llm", calls["llm"] + 1
        ),
    )
    monkeypatch.setattr(
        run_pagila_evaluation,
        "OpenAICompatibleLLMProvider",
        lambda *args, **kwargs: calls.__setitem__(
            "provider", calls["provider"] + 1
        ),
    )

    with pytest.raises(ValueError, match="freeze"):
        run_pagila_evaluation.evaluate_to_report(
            cases_path=Path("evaluation/cases/pagila_mvp.jsonl"),
            baseline_path=Path("evaluation/pagila_baseline.json"),
            report_path=Path("unused.json"),
            env_file=Path(".env"),
        )

    assert calls == {
        "target": 0,
        "connector": 0,
        "llm": 0,
        "provider": 0,
    }
