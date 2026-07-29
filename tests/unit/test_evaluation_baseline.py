import hashlib
import json
from pathlib import Path

import pytest

from app.config import DatabaseSettings
from evaluation import baseline as evaluation_baseline
from evaluation.baseline import (
    RuntimeBaselineObservation,
    build_frozen_evaluation_baseline,
    database_execution_baseline,
    normalized_dump_sha256,
    verify_evaluation_baseline,
    verify_static_evaluation_freeze,
)
from evaluation.report import (
    GoldCasesBaseline,
    PagilaBaseline,
    PostgreSQLBaseline,
    RuntimeSnapshotBaseline,
    load_baseline,
    write_baseline_atomic,
)


BASELINE_PATH = Path("evaluation/pagila_baseline.json")
MANIFEST_PATH = Path("infrastructure/pagila/manifest.json")
FIXTURE_DIR = Path("tests/fixtures/pagila/upstream")


def _database_settings(**changes: object) -> DatabaseSettings:
    fields: dict[str, object] = {
        "dsn": (
            "postgresql://text_to_sql_reader:secret"
            "@127.0.0.1:55432/pagila"
        ),
    }
    fields.update(changes)
    return DatabaseSettings(**fields)


def _runtime(**changes: object) -> RuntimeBaselineObservation:
    fields: dict[str, object] = {
        "image": (
            "postgres:16.14-bookworm@sha256:"
            "92620daddcd947f8d5ab5ba66e848702fe443d87fed30c4cea8e389fd78dfc55"
        ),
        "server_version": "16.14 (Debian 16.14-1.pgdg12+1)",
        "database_dump_sha256": (
            "e584f0beb3817d1a6f3e35518192ba66cc8b14c50df08c34527d5b15e77bd567"
        ),
        "database_schema_sha256": (
            "74de0ad271945ff3ce8e21d9065d1c0178f01994a8f25c613afebcebed5933b2"
        ),
        "film_row_count": 1000,
    }
    fields.update(changes)
    return RuntimeBaselineObservation(**fields)


def test_verifies_locked_static_and_runtime_baseline() -> None:
    verify_evaluation_baseline(
        load_baseline(BASELINE_PATH),
        manifest_path=MANIFEST_PATH,
        fixture_dir=FIXTURE_DIR,
        runtime=_runtime(),
    )


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("server_version", "16.13"),
        ("database_dump_sha256", "0" * 64),
        ("database_schema_sha256", "0" * 64),
        ("film_row_count", 999),
    ],
)
def test_rejects_runtime_baseline_drift(
    change: str,
    value: object,
) -> None:
    with pytest.raises(ValueError, match="baseline"):
        verify_evaluation_baseline(
            load_baseline(BASELINE_PATH),
            manifest_path=MANIFEST_PATH,
            fixture_dir=FIXTURE_DIR,
            runtime=_runtime(**{change: value}),
        )


def test_rejects_fixture_content_drift(tmp_path: Path) -> None:
    for name in ("pagila-schema.sql", "pagila-data.sql"):
        (tmp_path / name).write_bytes(
            (FIXTURE_DIR / name).read_bytes()
        )
    (tmp_path / "pagila-data.sql").write_text(
        "changed",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="baseline"):
        verify_evaluation_baseline(
            load_baseline(BASELINE_PATH),
            manifest_path=MANIFEST_PATH,
            fixture_dir=tmp_path,
            runtime=_runtime(),
        )


def test_dump_hash_normalizes_only_matching_restrict_nonce() -> None:
    first = (
        b"header\n\\restrict ABC123\nDATA\n"
        b"\\unrestrict ABC123\n"
    )
    second = (
        b"header\n\\restrict XYZ789\nDATA\n"
        b"\\unrestrict XYZ789\n"
    )

    assert normalized_dump_sha256(first) == normalized_dump_sha256(
        second
    )
    assert normalized_dump_sha256(first) == hashlib.sha256(
        b"header\n\\restrict TOKEN\nDATA\n"
        b"\\unrestrict TOKEN\n"
    ).hexdigest()


def test_dump_hash_rejects_missing_or_mismatched_nonce() -> None:
    with pytest.raises(ValueError, match="dump"):
        normalized_dump_sha256(b"no control lines\n")
    with pytest.raises(ValueError, match="dump"):
        normalized_dump_sha256(
            b"\\restrict FIRST\n\\unrestrict SECOND\n"
        )


def test_frozen_baseline_self_hash_and_static_anchors(
    tmp_path: Path,
) -> None:
    source_dir = Path("infrastructure/pagila")
    artifact_dir = tmp_path / "semantic"
    artifact_dir.mkdir()
    for name in (
        "view_semantic_candidates.json",
        "view_semantic_review.json",
        "view_semantics.json",
    ):
        (artifact_dir / name).write_bytes(
            (source_dir / name).read_bytes()
        )
    semantic_path = artifact_dir / "view_semantics.json"
    semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
    baseline = build_frozen_evaluation_baseline(
        pagila=PagilaBaseline(
            source="https://example.invalid/pagila",
            tag="v1",
            commit="1" * 40,
            archive_sha256="2" * 64,
            schema_sha256="3" * 64,
            data_sha256="4" * 64,
        ),
        postgresql=PostgreSQLBaseline(
            image="postgres@example",
            server_version="16.14",
        ),
        runtime_snapshot=RuntimeSnapshotBaseline(
            checksum_algorithm="synthetic",
            database_dump_sha256="5" * 64,
            database_schema_sha256=(
                semantic["database_schema_sha256"]
            ),
            film_row_count=1000,
        ),
        gold_cases=GoldCasesBaseline(
            initial_file_sha256="6" * 64,
            status_neutral_sha256="7" * 64,
        ),
        semantic_manifest_path=semantic_path,
        root=Path("."),
        database_execution=database_execution_baseline(
            _database_settings()
        ),
        model_config_sha256="8" * 64,
    )
    path = tmp_path / "baseline.json"
    write_baseline_atomic(path, baseline)

    loaded = load_baseline(path)
    assert loaded.software.installed_distributions
    verify_static_evaluation_freeze(
        loaded,
        semantic_manifest_path=semantic_path,
        root=Path("."),
        model_config_sha256="8" * 64,
    )

    original_semantic = semantic_path.read_bytes()
    forged_manifest = json.loads(original_semantic)
    forged_entry = dict(forged_manifest["entries"][0])
    forged_entry["alias"] = "forged_alias"
    forged_entry["source_definition_set_sha256"] = "a" * 64
    forged_entry["approved_evidence_set_sha256"] = "b" * 64
    forged_entry["approved_review_set_sha256"] = "c" * 64
    forged_manifest["entries"].append(forged_entry)
    semantic_path.write_text(
        json.dumps(forged_manifest),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="freeze"):
        build_frozen_evaluation_baseline(
            pagila=baseline.pagila,
            postgresql=baseline.postgresql,
            runtime_snapshot=baseline.runtime_snapshot,
            gold_cases=baseline.gold_cases,
            semantic_manifest_path=semantic_path,
            root=Path("."),
            database_execution=baseline.database_execution,
            model_config_sha256="8" * 64,
        )
    semantic_path.write_bytes(original_semantic)

    candidates_path = (
        artifact_dir / "view_semantic_candidates.json"
    )
    candidates = json.loads(
        candidates_path.read_text(encoding="utf-8")
    )
    candidates["candidates"][0]["alias"] = "forged"
    candidates_path.write_text(
        json.dumps(candidates),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="freeze"):
        verify_static_evaluation_freeze(
            loaded,
            semantic_manifest_path=semantic_path,
            root=Path("."),
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["software"]["prompt_version"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="baseline"):
        load_baseline(path)


def test_database_execution_freeze_excludes_only_password() -> None:
    first = database_execution_baseline(_database_settings())
    second = database_execution_baseline(
        _database_settings(
            dsn=(
                "postgresql://text_to_sql_reader:rotated"
                "@127.0.0.1:55432/pagila"
            )
        )
    )

    assert first == second
    rendered = first.model_dump_json()
    assert "secret" not in rendered
    assert "rotated" not in rendered
    assert "password" not in rendered
    assert "dsn" not in rendered


@pytest.mark.parametrize(
    "change",
    [
        {"min_pool_size": 2},
        {"max_pool_size": 3},
        {"pool_timeout_seconds": 4.0},
        {"statement_timeout_seconds": 29},
        {"max_result_rows": 999},
        {"connection_retry_count": 2},
    ],
)
def test_database_execution_freeze_detects_behavior_drift(
    change: dict[str, object],
) -> None:
    assert database_execution_baseline(
        _database_settings(**change)
    ) != database_execution_baseline(_database_settings())


def test_database_execution_freeze_rejects_dsn_behavior_overrides() -> None:
    with pytest.raises(ValueError, match="execution settings"):
        database_execution_baseline(
            _database_settings(
                dsn=(
                    "postgresql://text_to_sql_reader:secret"
                    "@127.0.0.1:55432/pagila"
                    "?options=-c%20statement_timeout%3D0"
                )
            )
        )


def test_static_freeze_detects_installed_distribution_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_dir = Path("infrastructure/pagila")
    artifact_dir = tmp_path / "semantic"
    artifact_dir.mkdir()
    for name in (
        "view_semantic_candidates.json",
        "view_semantic_review.json",
        "view_semantics.json",
    ):
        (artifact_dir / name).write_bytes(
            (source_dir / name).read_bytes()
        )
    semantic_path = artifact_dir / "view_semantics.json"
    semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
    baseline = build_frozen_evaluation_baseline(
        pagila=PagilaBaseline(
            source="https://example.invalid/pagila",
            tag="v1",
            commit="1" * 40,
            archive_sha256="2" * 64,
            schema_sha256="3" * 64,
            data_sha256="4" * 64,
        ),
        postgresql=PostgreSQLBaseline(
            image="postgres@example",
            server_version="16.14",
        ),
        runtime_snapshot=RuntimeSnapshotBaseline(
            checksum_algorithm="synthetic",
            database_dump_sha256="5" * 64,
            database_schema_sha256=semantic[
                "database_schema_sha256"
            ],
            film_row_count=1000,
        ),
        gold_cases=GoldCasesBaseline(
            initial_file_sha256="6" * 64,
            status_neutral_sha256="7" * 64,
        ),
        semantic_manifest_path=semantic_path,
        root=Path("."),
        database_execution=database_execution_baseline(
            _database_settings()
        ),
        model_config_sha256="8" * 64,
    )
    monkeypatch.setattr(
        evaluation_baseline,
        "installed_behavior_distributions",
        lambda: ("fastapi==0.0.0",),
    )

    with pytest.raises(ValueError, match="freeze"):
        verify_static_evaluation_freeze(
            baseline,
            semantic_manifest_path=semantic_path,
            root=Path("."),
        )
