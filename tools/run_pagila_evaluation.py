from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from ipaddress import ip_address
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict
from pydantic import ValidationError

from app.api.bootstrap import (
    PAGILA_MVP_ALLOWED_SCHEMAS,
    PAGILA_MVP_ALLOWED_TABLES,
)
from app.config import (
    DatabaseSettings,
    EmbeddingSettings,
    LLMSettings,
    load_database_settings,
    load_embedding_settings,
    load_llm_route_settings,
)
from app.connectors.postgresql import PostgreSQLConnector
from app.connectors.view_semantics import (
    FrozenSemanticConnector,
    load_view_semantic_manifest,
)
from app.connectors.view_semantics_lock import (
    PAGILA_DATABASE_SCHEMA_SHA256,
    VIEW_SEMANTIC_MANIFEST_PATH,
    VIEW_SEMANTIC_MANIFEST_SHA256,
)
from app.generation import (
    ModelRoutingRuntime,
    OpenAICompatibleLLMProvider,
    build_configured_model_routing_runtime,
)
from app.generation.models import PROMPT_VERSION
from app.generation.provider import PROVIDER_CONTRACT_VERSION
from app.observability import TraceRecord
from app.schema_linking import (
    EmbeddingIndexRegistry,
    OpenAICompatibleEmbeddingProvider,
    RetrievalRuntime,
)
from evaluation.baseline import (
    RuntimeBaselineObservation,
    build_frozen_evaluation_baseline,
    database_execution_baseline,
    normalized_dump_sha256,
    verify_database_execution_freeze,
    verify_evaluation_baseline,
    verify_static_evaluation_freeze,
)
from evaluation.code_freeze import (
    build_stage1_public_configuration,
    controlled_code_sha256,
    load_stage1_calibration_freeze,
    load_stage1_selected_configuration,
    verify_stage1_calibration_freeze,
)
from evaluation.loader import (
    load_case_suite,
    load_retrieval_routing_suites,
)
from evaluation.models import AuditStatus, CaseStatus
from evaluation.report import (
    EvaluationBaseline,
    EvaluationReport,
    RuntimeSnapshotBaseline,
    build_evaluation_report,
    load_baseline,
    load_baseline_source,
    load_report,
    require_report_baseline,
    review_case,
    write_baseline_atomic,
    write_report_atomic,
)
from evaluation.runner import evaluate_case
from evaluation.status import mark_case_verified

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_STAGE1_SELECTED_CONFIGURATION_PATH = (
    _REPOSITORY_ROOT
    / "evaluation"
    / "stage1_selected_configuration.json"
)
_STAGE1_CALIBRATION_FREEZE_PATH = (
    _REPOSITORY_ROOT
    / "evaluation"
    / "stage1_calibration_freeze.json"
)
_STAGE1_DEVELOPMENT_CASES_PATH = (
    _REPOSITORY_ROOT
    / "evaluation"
    / "cases"
    / "retrieval_routing_development.jsonl"
)
_STAGE1_CALIBRATION_CASES_PATH = (
    _REPOSITORY_ROOT
    / "evaluation"
    / "cases"
    / "retrieval_routing_calibration.jsonl"
)


class _DiscardTraceSink:
    def emit(self, record: TraceRecord) -> None:
        del record


def _docker_output(
    container_name: str,
    arguments: Sequence[str],
) -> bytes:
    if re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}",
        container_name,
    ) is None:
        raise ValueError("evaluation runtime probe failed")
    try:
        completed = subprocess.run(
            ["docker", *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("evaluation runtime probe failed") from None
    if completed.returncode != 0:
        raise ValueError("evaluation runtime probe failed")
    return completed.stdout


def collect_runtime_observation(
    container_name: str,
) -> RuntimeBaselineObservation:
    try:
        image = _docker_output(
            container_name,
            ("inspect", "--format", "{{.Config.Image}}", container_name),
        ).decode("utf-8", errors="strict").strip()
        version_and_count = _docker_output(
            container_name,
            (
                "exec",
                container_name,
                "psql",
                "--username",
                "postgres",
                "--dbname",
                "pagila",
                "--tuples-only",
                "--no-align",
                "--command",
                (
                    "SELECT current_setting('server_version'), count(*) "
                    "FROM film GROUP BY 1"
                ),
            ),
        ).decode("utf-8", errors="strict").strip()
        dump = _docker_output(
            container_name,
            (
                "exec",
                container_name,
                "pg_dump",
                "--username",
                "postgres",
                "--dbname",
                "pagila",
                "--data-only",
                "--no-owner",
                "--no-privileges",
            ),
        )
        schema_dump = _docker_output(
            container_name,
            (
                "exec",
                container_name,
                "pg_dump",
                "--username",
                "postgres",
                "--dbname",
                "pagila",
                "--schema-only",
                "--no-owner",
                "--no-privileges",
            ),
        )
        server_version, raw_count = version_and_count.split("|")
        film_row_count = int(raw_count)
        database_dump_sha256 = normalized_dump_sha256(dump)
        database_schema_sha256 = normalized_dump_sha256(
            schema_dump
        )
    except (ValueError, UnicodeError):
        raise ValueError("evaluation runtime probe failed") from None
    return RuntimeBaselineObservation(
        image=image,
        server_version=server_version,
        database_dump_sha256=database_dump_sha256,
        database_schema_sha256=database_schema_sha256,
        film_row_count=film_row_count,
    )


def _is_loopback_host(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def verify_database_target(
    settings: DatabaseSettings,
    *,
    container_name: str,
) -> None:
    try:
        connection = conninfo_to_dict(settings.dsn_value)
        host = connection.get("host", "")
        port = int(connection.get("port", "5432"))
        user = connection.get("user", "")
        output = _docker_output(
            container_name,
            ("port", container_name, "5432/tcp"),
        ).decode("utf-8", errors="strict")
        lines = tuple(
            line.strip()
            for line in output.splitlines()
            if line.strip()
        )
        matches = tuple(
            re.fullmatch(
                r"(?:[0-9.]+|\[[0-9A-Fa-f:]+\]):([0-9]{1,5})",
                line,
            )
            for line in lines
        )
        published_ports = {
            int(match.group(1))
            for match in matches
            if match is not None
        }
    except (TypeError, ValueError, UnicodeError):
        raise ValueError(
            "evaluation database target does not match"
        ) from None
    if (
        set(connection)
        - {"host", "port", "dbname", "user", "password"}
        or not lines
        or any(match is None for match in matches)
        or not 1 <= port <= 65535
        or not _is_loopback_host(host)
        or port not in published_ports
        or user != "text_to_sql_reader"
    ):
        raise ValueError("evaluation database target does not match")


def verify_evaluation_environment(
    *,
    baseline: EvaluationBaseline,
    container_name: str,
) -> None:
    verify_evaluation_baseline(
        baseline,
        manifest_path=Path("infrastructure/pagila/manifest.json"),
        fixture_dir=Path("tests/fixtures/pagila/upstream"),
        runtime=collect_runtime_observation(container_name),
    )


def model_config_hash(
    settings: LLMSettings,
    *,
    semantic_manifest_sha256: str,
    controlled_code_sha256: str,
) -> str:
    if (
        re.fullmatch(
            r"[0-9a-f]{64}",
            semantic_manifest_sha256,
        )
        is None
        or re.fullmatch(
            r"[0-9a-f]{64}",
            controlled_code_sha256,
        )
        is None
    ):
        raise ValueError("model configuration is invalid")
    payload = json.dumps(
        {
            "base_url": str(settings.base_url),
            "model": settings.model,
            "temperature": settings.temperature,
            "timeout_seconds": settings.timeout_seconds,
            "prompt_contract_version": PROMPT_VERSION,
            "provider_contract_version": (
                PROVIDER_CONTRACT_VERSION
            ),
            "semantic_manifest_sha256": (
                semantic_manifest_sha256
            ),
            "controlled_code_sha256": controlled_code_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_optional_embedding_settings(
    env_file: Path,
) -> EmbeddingSettings | None:
    required_locations = {
        ("base_url",),
        ("model",),
        ("dimension",),
    }
    try:
        return load_embedding_settings(env_file)
    except ValidationError as error:
        issues = error.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )
        if (
            len(issues) == len(required_locations)
            and {
                tuple(issue.get("loc", ()))
                for issue in issues
            }
            == required_locations
            and all(
                issue.get("type") == "missing"
                for issue in issues
            )
        ):
            return None
        raise ValueError(
            "embedding settings are invalid"
        ) from None
    except ValueError:
        raise ValueError(
            "embedding settings are invalid"
        ) from None


def _load_required_embedding_settings(
    env_file: Path,
) -> EmbeddingSettings:
    settings = _load_optional_embedding_settings(env_file)
    if settings is None:
        raise ValueError("embedding settings are required")
    return settings


def _build_stage1_runtimes(
    *,
    env_file: Path,
    semantic_version: str,
) -> tuple[
    ModelRoutingRuntime,
    RetrievalRuntime,
    dict[str, object],
]:
    llm_route_settings = load_llm_route_settings(env_file)
    declared_llm_settings = {
        "simple": llm_route_settings.simple,
        "standard": llm_route_settings.standard,
        "complex": llm_route_settings.complex,
    }
    if llm_route_settings.fallback is not None:
        declared_llm_settings["fallback"] = (
            llm_route_settings.fallback
        )
    model_routing = build_configured_model_routing_runtime(
        settings=llm_route_settings,
        providers={
            provider_key: OpenAICompatibleLLMProvider(
                provider_settings
            )
            for provider_key, provider_settings
            in declared_llm_settings.items()
        },
    )
    embedding_settings = _load_required_embedding_settings(
        env_file
    )
    retrieval_runtime = RetrievalRuntime(
        provider=OpenAICompatibleEmbeddingProvider(
            embedding_settings
        ),
        registry=EmbeddingIndexRegistry(),
        semantic_version=semantic_version,
    )
    public_configuration = build_stage1_public_configuration(
        embedding_settings=embedding_settings,
        retrieval_runtime=retrieval_runtime,
        model_routing=model_routing,
    )
    return (
        model_routing,
        retrieval_runtime,
        public_configuration,
    )


def _verify_stage1_runtime_freeze(
    public_configuration: dict[str, object],
) -> str:
    selected = load_stage1_selected_configuration(
        _STAGE1_SELECTED_CONFIGURATION_PATH
    )
    freeze = load_stage1_calibration_freeze(
        _STAGE1_CALIBRATION_FREEZE_PATH
    )
    suites = load_retrieval_routing_suites(
        _STAGE1_DEVELOPMENT_CASES_PATH,
        _STAGE1_CALIBRATION_CASES_PATH,
    )
    if selected.public_configuration != public_configuration:
        raise ValueError(
            "stage1 runtime configuration does not match freeze"
        )
    verify_stage1_calibration_freeze(
        freeze,
        development_file_sha256=(
            suites.development.raw_sha256
        ),
        development_normalized_sha256=(
            suites.development.normalized_sha256
        ),
        calibration_file_sha256=(
            suites.calibration.raw_sha256
        ),
        calibration_normalized_sha256=(
            suites.calibration.normalized_sha256
        ),
        public_configuration=public_configuration,
        controlled_code_sha256_value=(
            controlled_code_sha256(_REPOSITORY_ROOT)
        ),
    )
    if freeze.stage1_config_sha256 != selected.stage1_config_sha256:
        raise ValueError(
            "stage1 runtime configuration does not match freeze"
        )
    return selected.stage1_config_sha256


def freeze_baseline(
    *,
    source_baseline_path: Path,
    output_path: Path,
    cases_path: Path,
    env_file: Path,
    pagila_container: str = "text-to-sql-pagila-postgres",
) -> None:
    suite = load_case_suite(cases_path)
    source = load_baseline_source(source_baseline_path)
    if (
        any(
            case.status is not CaseStatus.DRAFT
            for case in suite.cases
        )
        or suite.file_sha256
        != source.gold_cases.initial_file_sha256
        or suite.status_neutral_sha256
        != source.gold_cases.status_neutral_sha256
    ):
        raise ValueError("Gold cases must be exact and all draft")
    runtime = collect_runtime_observation(pagila_container)
    verify_evaluation_baseline(
        source,
        manifest_path=Path(
            "infrastructure/pagila/manifest.json"
        ),
        fixture_dir=Path("tests/fixtures/pagila/upstream"),
        runtime=runtime,
    )
    database_settings = load_database_settings(env_file)
    if database_settings.datasource_id != "pagila":
        raise ValueError("evaluation datasource must be pagila")
    verify_database_target(
        database_settings,
        container_name=pagila_container,
    )
    connector = PostgreSQLConnector(database_settings)
    connector.open()
    try:
        snapshot = connector.read_metadata(
            PAGILA_MVP_ALLOWED_SCHEMAS,
            PAGILA_MVP_ALLOWED_TABLES,
        )
        manifest = load_view_semantic_manifest(
            VIEW_SEMANTIC_MANIFEST_PATH,
            expected_sha256=VIEW_SEMANTIC_MANIFEST_SHA256,
            snapshot=snapshot,
            datasource_id=database_settings.datasource_id,
            database_schema_sha256=(
                PAGILA_DATABASE_SCHEMA_SHA256
            ),
            allowed_schemas=PAGILA_MVP_ALLOWED_SCHEMAS,
            allowed_tables=PAGILA_MVP_ALLOWED_TABLES,
        )
        (
            _,
            _,
            public_configuration,
        ) = _build_stage1_runtimes(
            env_file=env_file,
            semantic_version=(
                manifest.enriched_schema_version
            ),
        )
        config_sha256 = _verify_stage1_runtime_freeze(
            public_configuration
        )
        baseline = build_frozen_evaluation_baseline(
            pagila=source.pagila,
            postgresql=source.postgresql,
            runtime_snapshot=RuntimeSnapshotBaseline(
                checksum_algorithm=(
                    source.runtime_snapshot.checksum_algorithm
                ),
                database_dump_sha256=(
                    runtime.database_dump_sha256
                ),
                database_schema_sha256=(
                    runtime.database_schema_sha256
                ),
                film_row_count=runtime.film_row_count,
            ),
            gold_cases=source.gold_cases,
            semantic_manifest_path=(
                VIEW_SEMANTIC_MANIFEST_PATH
            ),
            root=_REPOSITORY_ROOT,
            database_execution=database_execution_baseline(
                database_settings
            ),
            model_config_sha256=config_sha256,
        )
        verify_static_evaluation_freeze(
            baseline,
            semantic_manifest_path=VIEW_SEMANTIC_MANIFEST_PATH,
            root=_REPOSITORY_ROOT,
            model_config_sha256=config_sha256,
        )
        write_baseline_atomic(output_path, baseline)
    finally:
        connector.close()


def evaluate_to_report(
    *,
    cases_path: Path,
    baseline_path: Path,
    report_path: Path,
    env_file: Path,
    pagila_container: str = "text-to-sql-pagila-postgres",
) -> EvaluationReport:
    suite = load_case_suite(cases_path)
    baseline = load_baseline(baseline_path)
    if any(
        case.status is not CaseStatus.DRAFT
        for case in suite.cases
    ):
        raise ValueError("Gold cases must be all draft")
    if (
        suite.file_sha256
        != baseline.gold_cases.initial_file_sha256
    ):
        raise ValueError("Gold draft file hash does not match")
    if (
        suite.status_neutral_sha256
        != baseline.gold_cases.status_neutral_sha256
    ):
        raise ValueError("Gold content hash does not match")
    if (
        baseline.semantic.manifest_sha256
        != VIEW_SEMANTIC_MANIFEST_SHA256
        or baseline.semantic.database_schema_sha256
        != PAGILA_DATABASE_SCHEMA_SHA256
    ):
        raise ValueError("evaluation freeze does not match")
    verify_static_evaluation_freeze(
        baseline,
        semantic_manifest_path=VIEW_SEMANTIC_MANIFEST_PATH,
        root=_REPOSITORY_ROOT,
    )
    verify_evaluation_environment(
        baseline=baseline,
        container_name=pagila_container,
    )

    database_settings = load_database_settings(env_file)
    if database_settings.datasource_id != "pagila":
        raise ValueError("evaluation datasource must be pagila")
    verify_database_execution_freeze(
        baseline,
        database_settings,
    )
    verify_database_target(
        database_settings,
        container_name=pagila_container,
    )

    connector = PostgreSQLConnector(database_settings)
    connector.open()
    try:
        snapshot = connector.read_metadata(
            PAGILA_MVP_ALLOWED_SCHEMAS,
            PAGILA_MVP_ALLOWED_TABLES,
        )
        manifest = load_view_semantic_manifest(
            VIEW_SEMANTIC_MANIFEST_PATH,
            expected_sha256=VIEW_SEMANTIC_MANIFEST_SHA256,
            snapshot=snapshot,
            datasource_id=database_settings.datasource_id,
            database_schema_sha256=(
                PAGILA_DATABASE_SCHEMA_SHA256
            ),
            allowed_schemas=PAGILA_MVP_ALLOWED_SCHEMAS,
            allowed_tables=PAGILA_MVP_ALLOWED_TABLES,
        )
        semantic_connector = FrozenSemanticConnector(
            connector,
            manifest,
        )
        (
            model_routing,
            retrieval_runtime,
            public_configuration,
        ) = _build_stage1_runtimes(
            env_file=env_file,
            semantic_version=(
                manifest.enriched_schema_version
            ),
        )
        current_model_config_hash = (
            _verify_stage1_runtime_freeze(
                public_configuration
            )
        )
        verify_static_evaluation_freeze(
            baseline,
            semantic_manifest_path=VIEW_SEMANTIC_MANIFEST_PATH,
            root=_REPOSITORY_ROOT,
            model_config_sha256=current_model_config_hash,
        )
        evaluations = tuple(
            evaluate_case(
                case,
                evaluation_baseline_id=(
                    baseline.evaluation_baseline_id
                ),
                connector=semantic_connector,
                model_routing=model_routing,
                retrieval_runtime=retrieval_runtime,
                trace_sink=_DiscardTraceSink(),
            )
            for case in suite.cases
        )
    finally:
        connector.close()

    verified_count = sum(
        case.status is CaseStatus.VERIFIED
        for case in suite.cases
    )
    report = build_evaluation_report(
        evaluations,
        baseline=baseline,
        model_config_hash=current_model_config_hash,
        cases_file_sha256=suite.file_sha256,
        status_neutral_sha256=suite.status_neutral_sha256,
        verified_case_count=verified_count,
    )
    write_report_atomic(report_path, report)
    return report


def _refresh_report(
    cases_path: Path,
    report_path: Path,
    *,
    current_baseline: EvaluationBaseline,
) -> None:
    suite = load_case_suite(cases_path)
    report = load_report(report_path)
    require_report_baseline(report, current_baseline)
    verified_case_ids = {
        case.case_id
        for case in suite.cases
        if case.status is CaseStatus.VERIFIED
    }
    _require_verified_evidence(report, verified_case_ids)
    revised = build_evaluation_report(
        report.evaluations,
        baseline=current_baseline,
        model_config_hash=report.model_config_hash,
        cases_file_sha256=suite.file_sha256,
        status_neutral_sha256=suite.status_neutral_sha256,
        verified_case_count=sum(
            case.status is CaseStatus.VERIFIED
            for case in suite.cases
        ),
    )
    write_report_atomic(report_path, revised)


def _require_verified_evidence(
    report: EvaluationReport,
    case_ids: set[str],
) -> None:
    evaluations = {
        item.case_id: item for item in report.evaluations
    }
    for case_id in case_ids:
        item = evaluations.get(case_id)
        if (
            item is None
            or not item.passed
            or item.audit_status is not AuditStatus.APPROVED
        ):
            raise ValueError(
                "verified Gold status lacks approved evidence"
            )


def verify_case(
    cases_path: Path,
    report_path: Path,
    *,
    current_baseline: EvaluationBaseline,
    case_id: str,
) -> None:
    report = load_report(report_path)
    require_report_baseline(report, current_baseline)
    suite = load_case_suite(cases_path)
    verified_case_ids = {
        case.case_id
        for case in suite.cases
        if case.status is CaseStatus.VERIFIED
    }
    _require_verified_evidence(
        report,
        {*verified_case_ids, case_id},
    )
    mark_case_verified(
        cases_path,
        report_path,
        current_baseline=current_baseline,
        case_id=case_id,
        expected_status_neutral_sha256=(
            report.baseline.gold_cases.status_neutral_sha256
        ),
    )
    _refresh_report(
        cases_path,
        report_path,
        current_baseline=current_baseline,
    )


def _load_current_audit_baseline(
    path: Path,
) -> EvaluationBaseline:
    baseline = load_baseline(path)
    verify_static_evaluation_freeze(
        baseline,
        semantic_manifest_path=VIEW_SEMANTIC_MANIFEST_PATH,
        root=_REPOSITORY_ROOT,
    )
    return baseline


def _case_id(value: str) -> str:
    if (
        len(value) != 10
        or not value.startswith("PG-MVP-")
        or not value[-3:].isdigit()
    ):
        raise argparse.ArgumentTypeError("invalid Case ID")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run and audit the Pagila MVP evaluation.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    freeze = commands.add_parser("freeze-baseline")
    freeze.add_argument("--baseline", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--cases", type=Path, required=True)
    freeze.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
    )
    freeze.add_argument(
        "--pagila-container",
        default="text-to-sql-pagila-postgres",
    )

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--cases", type=Path, required=True)
    evaluate.add_argument("--baseline", type=Path, required=True)
    evaluate.add_argument("--report", type=Path, required=True)
    evaluate.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
    )
    evaluate.add_argument(
        "--pagila-container",
        default="text-to-sql-pagila-postgres",
    )

    review = commands.add_parser("review-case")
    review.add_argument("--report", type=Path, required=True)
    review.add_argument("--baseline", type=Path, required=True)
    review.add_argument("--case-id", type=_case_id, required=True)
    decision = review.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")

    verify = commands.add_parser("verify-case")
    verify.add_argument("--cases", type=Path, required=True)
    verify.add_argument("--report", type=Path, required=True)
    verify.add_argument("--baseline", type=Path, required=True)
    verify.add_argument("--case-id", type=_case_id, required=True)
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "freeze-baseline":
        freeze_baseline(
            source_baseline_path=arguments.baseline,
            output_path=arguments.output,
            cases_path=arguments.cases,
            env_file=arguments.env_file,
            pagila_container=arguments.pagila_container,
        )
        print("evaluation baseline frozen")
    elif arguments.command == "evaluate":
        report = evaluate_to_report(
            cases_path=arguments.cases,
            baseline_path=arguments.baseline,
            report_path=arguments.report,
            env_file=arguments.env_file,
            pagila_container=arguments.pagila_container,
        )
        for item in report.evaluations:
            print(
                item.case_id,
                item.code,
                item.audit_status.value,
            )
    elif arguments.command == "review-case":
        current_baseline = _load_current_audit_baseline(
            arguments.baseline
        )
        review_case(
            arguments.report,
            current_baseline=current_baseline,
            case_id=arguments.case_id,
            approved=arguments.approve,
        )
        print(
            arguments.case_id,
            "approved" if arguments.approve else "rejected",
        )
    else:
        current_baseline = _load_current_audit_baseline(
            arguments.baseline
        )
        verify_case(
            arguments.cases,
            arguments.report,
            current_baseline=current_baseline,
            case_id=arguments.case_id,
        )
        print(arguments.case_id, "verified")
    return 0


def main() -> None:
    try:
        raise SystemExit(run())
    except SystemExit:
        raise
    except Exception:
        print("evaluation command failed", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
