import json
import subprocess
from pathlib import Path

import pytest

from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.connectors.view_semantics import ViewDefinitionInput
from tools import freeze_view_semantics
from tools.freeze_view_semantics import FreezeInputs, run


SECRET_SQL = (
    "SELECT CASE WHEN a.is_archived "
    "THEN 'api_key_sk_never_store' ELSE '' END AS note "
    "FROM public.asset AS a"
)


def _inputs() -> FreezeInputs:
    snapshot = build_schema_snapshot(
        tables=(
            TableMetadata(
                schema_name="public",
                table_name="asset",
                relation_kind="table",
                comment=None,
                columns=(
                    ColumnMetadata(
                        schema_name="public",
                        table_name="asset",
                        column_name="is_archived",
                        ordinal_position=1,
                        data_type="bool",
                        formatted_type="boolean",
                        nullable=False,
                        comment=None,
                    ),
                ),
            ),
        ),
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )
    return FreezeInputs(
        snapshot=snapshot,
        definitions=(
            ViewDefinitionInput(
                schema_name="public",
                view_name="private_salary_view",
                sql=SECRET_SQL,
            ),
        ),
        allowed_schemas=("public",),
        allowed_tables=("public.asset",),
        database_schema_sha256="4" * 64,
    )


def _collector(*args: object, **kwargs: object) -> FreezeInputs:
    del args, kwargs
    return _inputs()


def test_candidate_artifact_and_cli_never_leak_rejected_source(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "candidates.json"
    run(
        [
            "candidates",
            "--baseline",
            str(tmp_path / "baseline.json"),
            "--output",
            str(output),
        ],
        collector=_collector,
    )

    artifact = output.read_text(encoding="utf-8")
    console = capsys.readouterr()
    combined = artifact + console.out + console.err

    assert json.loads(artifact)["candidates"] == []
    assert "api_key_sk_never_store" not in combined
    assert "private_salary_view" not in combined
    assert "SELECT CASE" not in combined
    assert "public.asset" not in combined


def test_collection_failure_does_not_print_raw_exception(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def failed_collector(*args: object, **kwargs: object):
        del args, kwargs
        raise RuntimeError(
            "postgresql://reader:password@host/db "
            + SECRET_SQL
        )

    with pytest.raises(ValueError, match="collection"):
        run(
            [
                "candidates",
                "--baseline",
                str(tmp_path / "baseline.json"),
                "--output",
                str(tmp_path / "unused.json"),
            ],
            collector=failed_collector,
        )

    captured = capsys.readouterr()
    assert "password" not in captured.out + captured.err
    assert SECRET_SQL not in captured.out + captured.err


def test_docker_catalog_failure_discards_secret_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def failed_run(*args: object, **kwargs: object):
        del args, kwargs
        return subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout=b"",
            stderr=(
                b"postgresql://reader:password@host/db "
                + SECRET_SQL.encode("utf-8")
            ),
        )

    monkeypatch.setattr(
        freeze_view_semantics.subprocess,
        "run",
        failed_run,
    )

    with pytest.raises(ValueError, match="collection"):
        freeze_view_semantics._collect_view_definitions(
            "pagila-test"
        )

    captured = capsys.readouterr()
    assert "password" not in captured.out + captured.err
    assert SECRET_SQL not in captured.out + captured.err
