from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.api.bootstrap import (
    PAGILA_MVP_ALLOWED_SCHEMAS,
    PAGILA_MVP_ALLOWED_TABLES,
)
from app.config import load_database_settings
from app.connectors.metadata import SchemaSnapshot
from app.connectors.postgresql import PostgreSQLConnector
from app.connectors.view_semantics import (
    ViewDefinitionInput,
    ViewSemanticCandidateLedger,
    ViewSemanticReview,
    build_view_semantic_manifest,
    build_view_semantic_review,
    extract_view_semantic_candidates,
    review_semantic_candidate,
    validate_view_semantic_candidate_ledger,
    validate_view_semantic_review,
)
from evaluation.report import load_baseline
from tools.run_pagila_evaluation import (
    verify_database_target,
    verify_evaluation_environment,
)

_VIEW_DEFINITIONS_SQL = """
WITH dependencies AS (
    SELECT
        rewrite.ev_class AS view_oid,
        array_agg(
            DISTINCT base_namespace.nspname || '.' || base_relation.relname
            ORDER BY base_namespace.nspname || '.' || base_relation.relname
        ) AS dependency_tables
    FROM pg_catalog.pg_rewrite AS rewrite
    JOIN pg_catalog.pg_depend AS dependency
      ON dependency.classid = 'pg_rewrite'::regclass
     AND dependency.objid = rewrite.oid
     AND dependency.refclassid = 'pg_class'::regclass
    JOIN pg_catalog.pg_class AS base_relation
      ON base_relation.oid = dependency.refobjid
     AND base_relation.relkind IN ('r', 'p')
    JOIN pg_catalog.pg_namespace AS base_namespace
      ON base_namespace.oid = base_relation.relnamespace
    GROUP BY rewrite.ev_class
)
SELECT json_build_object(
    'schema_name', view_namespace.nspname,
    'view_name', view_relation.relname,
    'sql', pg_get_viewdef(view_relation.oid, true),
    'dependency_tables',
        COALESCE(
            dependencies.dependency_tables,
            ARRAY[]::text[]
        )
)::text
FROM pg_catalog.pg_class AS view_relation
JOIN pg_catalog.pg_namespace AS view_namespace
  ON view_namespace.oid = view_relation.relnamespace
LEFT JOIN dependencies
  ON dependencies.view_oid = view_relation.oid
WHERE view_relation.relkind = 'v'
  AND view_namespace.nspname = 'public'
ORDER BY view_namespace.nspname, view_relation.relname
""".strip()


@dataclass(frozen=True, slots=True)
class FreezeInputs:
    snapshot: SchemaSnapshot
    definitions: tuple[ViewDefinitionInput, ...]
    allowed_schemas: tuple[str, ...]
    allowed_tables: tuple[str, ...]
    database_schema_sha256: str


Collector = Callable[..., FreezeInputs]


def _docker_output(
    container_name: str,
    arguments: Sequence[str],
) -> bytes:
    if re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}",
        container_name,
    ) is None:
        raise ValueError("view semantic collection failed")
    try:
        completed = subprocess.run(
            ["docker", *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError(
            "view semantic collection failed"
        ) from None
    if completed.returncode != 0:
        raise ValueError("view semantic collection failed")
    return completed.stdout


def _parse_view_definitions(
    payload: bytes,
) -> tuple[ViewDefinitionInput, ...]:
    definitions: list[ViewDefinitionInput] = []
    identities: set[tuple[str, str]] = set()
    try:
        text = payload.decode("utf-8", errors="strict")
        for raw_line in text.splitlines():
            if not raw_line:
                continue
            record = json.loads(raw_line)
            if (
                not isinstance(record, dict)
                or set(record)
                != {
                    "schema_name",
                    "view_name",
                    "sql",
                    "dependency_tables",
                }
                or not isinstance(record["schema_name"], str)
                or not isinstance(record["view_name"], str)
                or not isinstance(record["sql"], str)
                or not isinstance(
                    record["dependency_tables"],
                    list,
                )
                or any(
                    not isinstance(item, str) or "." not in item
                    for item in record["dependency_tables"]
                )
            ):
                raise ValueError
            identity = (
                record["schema_name"],
                record["view_name"],
            )
            if identity in identities:
                raise ValueError
            identities.add(identity)
            definitions.append(
                ViewDefinitionInput(
                    schema_name=record["schema_name"],
                    view_name=record["view_name"],
                    sql=record["sql"],
                    dependency_tables=tuple(
                        sorted(
                            set(record["dependency_tables"])
                        )
                    ),
                )
            )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ):
        raise ValueError(
            "view semantic catalog output is invalid"
        ) from None
    return tuple(definitions)


def _collect_view_definitions(
    container_name: str,
) -> tuple[ViewDefinitionInput, ...]:
    payload = _docker_output(
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
            _VIEW_DEFINITIONS_SQL,
        ),
    )
    return _parse_view_definitions(payload)


def _collect_freeze_inputs(
    *,
    baseline_path: Path,
    env_file: Path,
    container_name: str,
) -> FreezeInputs:
    baseline = load_baseline(baseline_path)
    verify_evaluation_environment(
        baseline=baseline,
        container_name=container_name,
    )
    settings = load_database_settings(env_file)
    if settings.datasource_id != "pagila":
        raise ValueError("view semantic collection failed")
    verify_database_target(
        settings,
        container_name=container_name,
    )
    connector = PostgreSQLConnector(settings)
    connector.open()
    try:
        snapshot = connector.read_metadata(
            PAGILA_MVP_ALLOWED_SCHEMAS,
            PAGILA_MVP_ALLOWED_TABLES,
        )
    finally:
        connector.close()
    return FreezeInputs(
        snapshot=snapshot,
        definitions=_collect_view_definitions(container_name),
        allowed_schemas=PAGILA_MVP_ALLOWED_SCHEMAS,
        allowed_tables=PAGILA_MVP_ALLOWED_TABLES,
        database_schema_sha256=(
            baseline.runtime_snapshot.database_schema_sha256
        ),
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _write_model(path: Path, model: object) -> None:
    serializer = getattr(model, "model_dump_json", None)
    if not callable(serializer):
        raise ValueError("view semantic artifact is invalid")
    _atomic_write(
        path,
        (serializer(indent=2) + "\n").encode("utf-8"),
    )


def _load_candidates(path: Path) -> ViewSemanticCandidateLedger:
    try:
        ledger = ViewSemanticCandidateLedger.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        validate_view_semantic_candidate_ledger(ledger)
        return ledger
    except (
        OSError,
        UnicodeDecodeError,
        ValidationError,
        ValueError,
    ):
        raise ValueError(
            "view semantic candidate artifact is invalid"
        ) from None


def _load_review(
    path: Path,
    ledger: ViewSemanticCandidateLedger,
    *,
    require_complete: bool,
) -> ViewSemanticReview:
    try:
        review = ViewSemanticReview.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        validate_view_semantic_review(
            ledger,
            review,
            require_complete=require_complete,
        )
        return review
    except (
        OSError,
        UnicodeDecodeError,
        ValidationError,
        ValueError,
    ):
        raise ValueError(
            "view semantic review artifact is invalid"
        ) from None


def _collect(
    collector: Collector,
    arguments: argparse.Namespace,
) -> FreezeInputs:
    try:
        result = collector(
            baseline_path=arguments.baseline,
            env_file=arguments.env_file,
            container_name=arguments.pagila_container,
        )
    except Exception:
        raise ValueError(
            "view semantic collection failed"
        ) from None
    if not isinstance(result, FreezeInputs):
        raise ValueError("view semantic collection failed")
    return result


def _extract(inputs: FreezeInputs) -> ViewSemanticCandidateLedger:
    return extract_view_semantic_candidates(
        inputs.definitions,
        snapshot=inputs.snapshot,
        allowed_schemas=inputs.allowed_schemas,
        allowed_tables=inputs.allowed_tables,
        database_schema_sha256=(
            inputs.database_schema_sha256
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze audited view semantic metadata.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    candidates = commands.add_parser("candidates")
    candidates.add_argument("--baseline", type=Path, required=True)
    candidates.add_argument("--output", type=Path, required=True)

    review = commands.add_parser("review")
    review.add_argument("--candidates", type=Path, required=True)
    review.add_argument("--review", type=Path, required=True)
    review.add_argument(
        "--evidence-sha256",
        required=True,
    )
    decision = review.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")

    freeze = commands.add_parser("freeze")
    freeze.add_argument("--candidates", type=Path, required=True)
    freeze.add_argument("--review", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument(
        "--datasource-id",
        default="pagila",
    )

    for command in (candidates, freeze):
        if command is freeze:
            command.add_argument(
                "--baseline",
                type=Path,
                default=Path("evaluation/pagila_baseline.json"),
            )
        command.add_argument(
            "--env-file",
            type=Path,
            default=Path(".env"),
        )
        command.add_argument(
            "--pagila-container",
            default="text-to-sql-pagila-postgres",
        )
    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    collector: Collector = _collect_freeze_inputs,
) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "candidates":
        _write_model(
            arguments.output,
            _extract(_collect(collector, arguments)),
        )
        print("view semantic candidates written")
        return 0

    ledger = _load_candidates(arguments.candidates)
    if arguments.command == "review":
        existing: tuple = ()
        if arguments.review.exists():
            existing = _load_review(
                arguments.review,
                ledger,
                require_complete=False,
            ).decisions
        if any(
            item.evidence_sha256 == arguments.evidence_sha256
            for item in existing
        ):
            raise ValueError("view semantic review is invalid")
        matches = tuple(
            candidate
            for candidate in ledger.candidates
            if candidate.evidence_sha256
            == arguments.evidence_sha256
        )
        if len(matches) != 1:
            raise ValueError("view semantic review is invalid")
        decision = review_semantic_candidate(
            matches[0],
            approved=arguments.approve,
        )
        review = build_view_semantic_review(
            ledger,
            (*existing, decision),
            require_complete=False,
        )
        _write_model(arguments.review, review)
        print("view semantic review recorded")
        return 0

    review = _load_review(
        arguments.review,
        ledger,
        require_complete=True,
    )
    inputs = _collect(collector, arguments)
    current = _extract(inputs)
    if current != ledger:
        raise ValueError(
            "view semantic candidate artifact is invalid"
        )
    manifest = build_view_semantic_manifest(
        ledger,
        review,
        snapshot=inputs.snapshot,
        datasource_id=arguments.datasource_id,
    )
    _write_model(arguments.output, manifest)
    print("view semantic manifest written")
    return 0


def main() -> None:
    try:
        raise SystemExit(run())
    except SystemExit:
        raise
    except Exception:
        print("view semantic command failed")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
