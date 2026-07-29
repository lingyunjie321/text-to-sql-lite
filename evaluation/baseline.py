from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import re
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from app.config import DatabaseSettings
from app.connectors.view_semantics import (
    ViewSemanticCandidateLedger,
    ViewSemanticManifest,
    ViewSemanticReview,
    validate_view_semantic_audit_bundle,
    validate_view_semantic_candidate_ledger,
    validate_view_semantic_review,
)
from app.generation.models import PROMPT_VERSION
from app.generation.provider import PROVIDER_CONTRACT_VERSION
from evaluation.code_freeze import (
    controlled_code_sha256,
    evaluation_baseline_id,
)
from evaluation.comparator import COMPARATOR_VERSION
from evaluation.report import (
    BASELINE_VERSION,
    REPORT_VERSION,
    DatabaseExecutionBaseline,
    EvaluationBaseline,
    EvaluationBaselineSource,
    GoldCasesBaseline,
    ModelConfigurationBaseline,
    PagilaBaseline,
    PostgreSQLBaseline,
    RuntimeSnapshotBaseline,
    SemanticBaseline,
    SoftwareBaseline,
)
from evaluation.runner import EVIDENCE_VERSION

_CONTROL_LINE = re.compile(
    rb"^\\(un)?restrict ([A-Za-z0-9]+)$",
    flags=re.MULTILINE,
)
_BEHAVIOR_DISTRIBUTIONS = (
    "annotated-doc",
    "annotated-types",
    "anyio",
    "fastapi",
    "langchain-core",
    "langgraph",
    "langgraph-checkpoint",
    "langgraph-prebuilt",
    "langgraph-sdk",
    "psycopg",
    "psycopg-binary",
    "psycopg-pool",
    "pydantic",
    "pydantic-core",
    "pydantic-settings",
    "python-dotenv",
    "sqlglot",
    "starlette",
    "typing-extensions",
    "typing-inspection",
    "xxhash",
)
_ALLOWED_DSN_KEYS = frozenset(
    {"host", "port", "dbname", "user", "password"}
)


class RuntimeBaselineObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    image: str = Field(min_length=1)
    server_version: str = Field(min_length=1)
    database_dump_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    database_schema_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    film_row_count: int = Field(ge=0)


def normalized_dump_sha256(payload: bytes) -> str:
    matches = tuple(_CONTROL_LINE.finditer(payload))
    if (
        len(matches) != 2
        or matches[0].group(1) is not None
        or matches[1].group(1) != b"un"
        or matches[0].group(2) != matches[1].group(2)
    ):
        raise ValueError("runtime database dump is invalid")
    normalized = _CONTROL_LINE.sub(
        lambda match: (
            b"\\unrestrict TOKEN"
            if match.group(1) == b"un"
            else b"\\restrict TOKEN"
        ),
        payload,
    )
    return hashlib.sha256(normalized).hexdigest()


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        raise ValueError("evaluation baseline does not match") from None


def _load_semantic_manifest(
    path: Path,
) -> tuple[ViewSemanticManifest, str]:
    try:
        payload = path.read_bytes()
        manifest = ViewSemanticManifest.model_validate_json(payload)
        candidates = (
            ViewSemanticCandidateLedger.model_validate_json(
                (
                    path.parent
                    / "view_semantic_candidates.json"
                ).read_bytes()
            )
        )
        validate_view_semantic_candidate_ledger(candidates)
        review = ViewSemanticReview.model_validate_json(
            (
                path.parent / "view_semantic_review.json"
            ).read_bytes()
        )
        validate_view_semantic_review(
            candidates,
            review,
            require_complete=True,
        )
        validate_view_semantic_audit_bundle(
            candidates,
            review,
            manifest,
        )
        return manifest, hashlib.sha256(payload).hexdigest()
    except (OSError, ValidationError, ValueError):
        raise ValueError(
            "evaluation freeze does not match"
        ) from None


def _semantic_baseline(
    manifest: ViewSemanticManifest,
    *,
    manifest_sha256: str,
) -> SemanticBaseline:
    return SemanticBaseline(
        manifest_sha256=manifest_sha256,
        manifest_version=manifest.manifest_version,
        extractor_version=manifest.extractor_version,
        policy_version=manifest.policy_version,
        database_schema_sha256=(
            manifest.database_schema_sha256
        ),
        base_schema_version=manifest.base_schema_version,
        enriched_schema_version=(
            manifest.enriched_schema_version
        ),
        allowed_scope_sha256=manifest.allowed_scope_sha256,
        view_definitions_sha256=(
            manifest.view_definitions_sha256
        ),
        candidate_ledger_sha256=(
            manifest.candidate_ledger_sha256
        ),
        review_file_sha256=manifest.review_file_sha256,
    )


def _software_baseline(root: Path) -> SoftwareBaseline:
    return SoftwareBaseline(
        controlled_code_sha256=controlled_code_sha256(root),
        python_implementation=platform.python_implementation(),
        python_version=platform.python_version(),
        installed_distributions=installed_behavior_distributions(),
        prompt_version=PROMPT_VERSION,
        provider_contract_version=PROVIDER_CONTRACT_VERSION,
        comparator_version=COMPARATOR_VERSION,
        evidence_version=EVIDENCE_VERSION,
        report_version=REPORT_VERSION,
    )


def installed_behavior_distributions() -> tuple[str, ...]:
    versions: list[str] = []
    try:
        for name in _BEHAVIOR_DISTRIBUTIONS:
            version = importlib.metadata.version(name)
            normalized = re.sub(r"[-_.]+", "-", name).casefold()
            if (
                not version
                or re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9.+!_-]*",
                    version,
                )
                is None
            ):
                raise ValueError
            versions.append(f"{normalized}=={version}")
    except (
        importlib.metadata.PackageNotFoundError,
        ValueError,
    ):
        raise ValueError(
            "installed distribution fingerprint is invalid"
        ) from None
    result = tuple(sorted(versions))
    if len(result) != len(set(result)):
        raise ValueError(
            "installed distribution fingerprint is invalid"
        )
    return result


def database_execution_baseline(
    settings: DatabaseSettings,
) -> DatabaseExecutionBaseline:
    try:
        connection = conninfo_to_dict(settings.dsn_value)
        if (
            set(connection) - _ALLOWED_DSN_KEYS
            or not {"host", "dbname", "user"} <= set(connection)
        ):
            raise ValueError
        port = int(connection.get("port", "5432"))
        return DatabaseExecutionBaseline(
            datasource_id=settings.datasource_id,
            host=connection["host"],
            port=port,
            dbname=connection["dbname"],
            user=connection["user"],
            min_pool_size=settings.min_pool_size,
            max_pool_size=settings.max_pool_size,
            pool_timeout_seconds=settings.pool_timeout_seconds,
            statement_timeout_seconds=(
                settings.statement_timeout_seconds
            ),
            max_result_rows=settings.max_result_rows,
            connection_retry_count=settings.connection_retry_count,
        )
    except (KeyError, TypeError, ValueError):
        raise ValueError(
            "database execution settings are invalid"
        ) from None


def verify_database_execution_freeze(
    baseline: EvaluationBaseline,
    settings: DatabaseSettings,
) -> None:
    if (
        database_execution_baseline(settings)
        != baseline.database_execution
    ):
        raise ValueError("evaluation freeze does not match")


def build_frozen_evaluation_baseline(
    *,
    pagila: PagilaBaseline,
    postgresql: PostgreSQLBaseline,
    runtime_snapshot: RuntimeSnapshotBaseline,
    gold_cases: GoldCasesBaseline,
    semantic_manifest_path: Path,
    root: Path,
    database_execution: DatabaseExecutionBaseline,
    model_config_sha256: str,
) -> EvaluationBaseline:
    manifest, manifest_sha256 = _load_semantic_manifest(
        semantic_manifest_path
    )
    fields: dict[str, object] = {
        "baseline_version": BASELINE_VERSION,
        "pagila": pagila,
        "postgresql": postgresql,
        "runtime_snapshot": runtime_snapshot,
        "gold_cases": gold_cases,
        "semantic": _semantic_baseline(
            manifest,
            manifest_sha256=manifest_sha256,
        ),
        "software": _software_baseline(root),
        "database_execution": database_execution,
        "model_configuration": ModelConfigurationBaseline(
            config_sha256=model_config_sha256,
        ),
    }
    canonical = {
        key: (
            value.model_dump(mode="json")
            if isinstance(value, BaseModel)
            else value
        )
        for key, value in fields.items()
    }
    return EvaluationBaseline(
        **fields,
        evaluation_baseline_id=evaluation_baseline_id(
            canonical
        ),
    )


def verify_static_evaluation_freeze(
    baseline: EvaluationBaseline,
    *,
    semantic_manifest_path: Path,
    root: Path,
    model_config_sha256: str | None = None,
) -> None:
    try:
        manifest, manifest_sha256 = _load_semantic_manifest(
            semantic_manifest_path
        )
        semantic = _semantic_baseline(
            manifest,
            manifest_sha256=manifest_sha256,
        )
        software = _software_baseline(root)
    except ValueError:
        raise ValueError(
            "evaluation freeze does not match"
        ) from None
    if (
        baseline.semantic != semantic
        or baseline.software != software
        or (
            model_config_sha256 is not None
            and baseline.model_configuration.config_sha256
            != model_config_sha256
        )
    ):
        raise ValueError("evaluation freeze does not match")


def verify_evaluation_baseline(
    baseline: EvaluationBaseline | EvaluationBaselineSource,
    *,
    manifest_path: Path,
    fixture_dir: Path,
    runtime: RuntimeBaselineObservation,
) -> None:
    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        files = manifest["files"]
        schema = files["pagila-schema.sql"]
        data = files["pagila-data.sql"]
        static_matches = (
            manifest["source"] == baseline.pagila.source
            and manifest["tag"] == baseline.pagila.tag
            and manifest["commit"] == baseline.pagila.commit
            and manifest["archive_sha256"]
            == baseline.pagila.archive_sha256
            and schema["sha256"] == baseline.pagila.schema_sha256
            and data["sha256"] == baseline.pagila.data_sha256
            and _sha256(fixture_dir / "pagila-schema.sql")
            == baseline.pagila.schema_sha256
            and _sha256(fixture_dir / "pagila-data.sql")
            == baseline.pagila.data_sha256
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ):
        raise ValueError("evaluation baseline does not match") from None

    runtime_matches = (
        runtime.image == baseline.postgresql.image
        and runtime.server_version
        == baseline.postgresql.server_version
        and runtime.database_dump_sha256
        == baseline.runtime_snapshot.database_dump_sha256
        and runtime.database_schema_sha256
        == baseline.runtime_snapshot.database_schema_sha256
        and runtime.film_row_count
        == baseline.runtime_snapshot.film_row_count
    )
    if not static_matches or not runtime_matches:
        raise ValueError("evaluation baseline does not match")
