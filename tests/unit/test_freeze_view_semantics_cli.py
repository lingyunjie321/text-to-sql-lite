import json
from pathlib import Path

import pytest

from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.connectors.view_semantics import ViewDefinitionInput
from tools.freeze_view_semantics import (
    FreezeInputs,
    _parse_view_definitions,
    run,
)


def _snapshot():
    return build_schema_snapshot(
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
                        column_name="asset_id",
                        ordinal_position=1,
                        data_type="int4",
                        formatted_type="integer",
                        nullable=False,
                        comment=None,
                    ),
                    ColumnMetadata(
                        schema_name="public",
                        table_name="asset",
                        column_name="is_archived",
                        ordinal_position=2,
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


def _inputs() -> FreezeInputs:
    return FreezeInputs(
        snapshot=_snapshot(),
        definitions=(
            ViewDefinitionInput(
                schema_name="public",
                view_name="asset_directory",
                sql=(
                    "SELECT a.asset_id AS record_key, "
                    "CASE WHEN a.is_archived "
                    "THEN 'retired' ELSE '' END AS note "
                    "FROM public.asset AS a"
                ),
            ),
        ),
        allowed_schemas=("public",),
        allowed_tables=("public.asset",),
        database_schema_sha256="3" * 64,
    )


def _collector(*args: object, **kwargs: object) -> FreezeInputs:
    del args, kwargs
    return _inputs()


def _candidates(
    tmp_path: Path,
    name: str = "candidates.json",
) -> Path:
    path = tmp_path / name
    assert (
        run(
            [
                "candidates",
                "--baseline",
                str(tmp_path / "baseline.json"),
                "--output",
                str(path),
            ],
            collector=_collector,
        )
        == 0
    )
    return path


def test_candidate_generation_is_deterministic_and_unapproved(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = _candidates(tmp_path, "first.json")
    second = _candidates(tmp_path, "second.json")

    assert first.read_bytes() == second.read_bytes()
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert len(payload["candidates"]) == 2
    assert "approved" not in payload
    assert capsys.readouterr().out == (
        "view semantic candidates written\n"
        "view semantic candidates written\n"
    )


def test_freeze_refuses_until_every_candidate_is_reviewed(
    tmp_path: Path,
) -> None:
    candidates = _candidates(tmp_path)
    review = tmp_path / "review.json"

    with pytest.raises(ValueError, match="review"):
        run(
            [
                "freeze",
                "--candidates",
                str(candidates),
                "--review",
                str(review),
                "--output",
                str(tmp_path / "manifest.json"),
            ],
            collector=_collector,
        )


def test_review_updates_exactly_one_candidate_then_freezes(
    tmp_path: Path,
) -> None:
    candidates = _candidates(tmp_path)
    candidate_payload = json.loads(
        candidates.read_text(encoding="utf-8")
    )
    evidence = [
        item["evidence_sha256"]
        for item in candidate_payload["candidates"]
    ]
    review = tmp_path / "review.json"
    manifest = tmp_path / "manifest.json"

    assert (
        run(
            [
                "review",
                "--candidates",
                str(candidates),
                "--review",
                str(review),
                "--evidence-sha256",
                evidence[0],
                "--approve",
            ],
            collector=_collector,
        )
        == 0
    )
    first_review = json.loads(review.read_text(encoding="utf-8"))
    assert len(first_review["decisions"]) == 1

    assert (
        run(
            [
                "review",
                "--candidates",
                str(candidates),
                "--review",
                str(review),
                "--evidence-sha256",
                evidence[1],
                "--reject",
            ],
            collector=_collector,
        )
        == 0
    )
    second_review = json.loads(review.read_text(encoding="utf-8"))
    assert len(second_review["decisions"]) == 2

    assert (
        run(
            [
                "freeze",
                "--candidates",
                str(candidates),
                "--review",
                str(review),
                "--output",
                str(manifest),
                "--datasource-id",
                "synthetic",
            ],
            collector=_collector,
        )
        == 0
    )
    frozen = json.loads(manifest.read_text(encoding="utf-8"))
    assert len(frozen["entries"]) == 1
    assert (
        len(
            frozen["entries"][0][
                "approved_evidence_set_sha256"
            ]
        )
        == 64
    )
    assert "evidence_sha256" not in frozen["entries"][0]


def test_review_rejects_unknown_or_duplicate_evidence(
    tmp_path: Path,
) -> None:
    candidates = _candidates(tmp_path)
    payload = json.loads(candidates.read_text(encoding="utf-8"))
    evidence = payload["candidates"][0]["evidence_sha256"]
    review = tmp_path / "review.json"
    command = [
        "review",
        "--candidates",
        str(candidates),
        "--review",
        str(review),
        "--evidence-sha256",
        evidence,
        "--approve",
    ]
    assert run(command, collector=_collector) == 0

    with pytest.raises(ValueError, match="review"):
        run(command, collector=_collector)
    with pytest.raises(ValueError, match="review"):
        run(
            [
                *command[:-2],
                "0" * 64,
                "--approve",
            ],
            collector=_collector,
        )


def test_tampered_candidate_file_fails_closed(tmp_path: Path) -> None:
    candidates = _candidates(tmp_path)
    payload = json.loads(candidates.read_text(encoding="utf-8"))
    payload["candidates"][0]["alias"] = "forged"
    candidates.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="candidate"):
        run(
            [
                "review",
                "--candidates",
                str(candidates),
                "--review",
                str(tmp_path / "review.json"),
                "--evidence-sha256",
                payload["candidates"][0]["evidence_sha256"],
                "--approve",
            ],
            collector=_collector,
        )


def test_parses_catalog_view_rows_with_resolved_dependencies() -> None:
    definitions = _parse_view_definitions(
        (
            '{"schema_name":"public",'
            '"view_name":"asset_directory",'
            '"sql":" SELECT a.asset_id FROM asset a;",'
            '"dependency_tables":["public.asset"]}\n'
        ).encode("utf-8")
    )

    assert len(definitions) == 1
    assert definitions[0].schema_name == "public"
    assert definitions[0].dependency_tables == ("public.asset",)
    assert definitions[0].sql == (
        " SELECT a.asset_id FROM asset a;"
    )


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json\n",
        (
            b'{"schema_name":"public","view_name":"v",'
            b'"sql":"SELECT 1"}\n'
        ),
        (
            b'{"schema_name":"public","view_name":"v",'
            b'"sql":"SELECT 1","dependency_tables":[],'
            b'"unexpected":"value"}\n'
        ),
        (
            b'{"schema_name":"public","view_name":"v",'
            b'"sql":"SELECT 1","dependency_tables":["invalid"]}\n'
        ),
    ],
)
def test_rejects_malformed_catalog_view_rows(
    payload: bytes,
) -> None:
    with pytest.raises(ValueError, match="catalog"):
        _parse_view_definitions(payload)
