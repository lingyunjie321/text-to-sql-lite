from __future__ import annotations

import ast
import json
import tomllib
from collections.abc import Iterable, Sequence
from fnmatch import fnmatchcase
from pathlib import Path

from app.connectors.metadata import (
    ColumnMetadata,
    SchemaSnapshot,
    TableMetadata,
    build_schema_snapshot,
)
from app.connectors.models import ExecutionResult, ResultColumn
from app.generation import (
    GenerationResult,
    GeneratedSQL,
    LLMMessage,
)
from app.observability import TraceRecord
from evaluation import Difficulty, EvaluationCase, load_case_suite
from evaluation.runner import evaluate_case
from tests.routing_support import single_provider_test_routing

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_GOLD_CASES_PATH = (
    _REPOSITORY_ROOT / "evaluation/cases/pagila_mvp_all_draft.jsonl"
)
_PROTECTED_DATASET_PATHS = (
    "evaluation/cases/pagila_mvp_all_draft.jsonl",
    "evaluation/cases/retrieval_routing_development.jsonl",
    "evaluation/cases/retrieval_routing_calibration.jsonl",
)
_PROTECTED_DATASET_NAMES = frozenset(
    Path(path).name for path in _PROTECTED_DATASET_PATHS
)

_USER_PAYLOAD_KEYS = frozenset(
    {
        "allowed_functions",
        "candidate_fields",
        "candidate_tables",
        "dialect",
        "foreign_keys",
        "join_paths",
        "max_result_rows",
        "normalized_question",
        "normalized_time",
        "primary_keys",
        "prompt_version",
        "question",
        "schema_version",
    }
)
_CANDIDATE_TABLE_KEYS = frozenset(
    {
        "comment",
        "matched_tokens",
        "object_id",
        "relation_kind",
        "score",
    }
)
_CANDIDATE_FIELD_KEYS = frozenset(
    {
        "aliases",
        "comment",
        "formatted_type",
        "matched_tokens",
        "nullable",
        "object_id",
        "score",
    }
)
_FORBIDDEN_EVALUATION_KEYS = frozenset(
    {
        "case_id",
        "category",
        "comparison_mode",
        "difficulty",
        "expected",
        "expected_behavior",
        "expected_error_type",
        "expected_final_status",
        "fixture",
        "gold",
        "gold_fields",
        "gold_join_edges",
        "gold_result",
        "gold_result_source",
        "gold_sql",
        "gold_tables",
        "label",
        "labels",
        "numeric_tolerances",
        "order_sensitive",
        "result",
        "results",
        "status",
        "tags",
    }
)


def _film_snapshot() -> SchemaSnapshot:
    columns = (
        ("film_id", "integer"),
        ("title", "text"),
        ("rental_rate", "numeric"),
    )
    return build_schema_snapshot(
        tables=(
            TableMetadata(
                schema_name="public",
                table_name="film",
                relation_kind="table",
                comment="films 影片",
                columns=tuple(
                    ColumnMetadata(
                        schema_name="public",
                        table_name="film",
                        column_name=name,
                        ordinal_position=position,
                        data_type=data_type,
                        formatted_type=data_type,
                        nullable=False,
                        comment=None,
                    )
                    for position, (name, data_type) in enumerate(
                        columns,
                        start=1,
                    )
                ),
            ),
        ),
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )


def _film_result() -> ExecutionResult:
    return ExecutionResult(
        columns=(
            ResultColumn(name="film_id", type_oid=23),
            ResultColumn(name="title", type_oid=25),
            ResultColumn(name="rental_rate", type_oid=1700),
        ),
        rows=[[1, "ACADEMY DINOSAUR", "0.99"]],
        returned_row_count=1,
        truncated=False,
        execution_time_ms=1.0,
    )


class _SuccessfulConnector:
    def __init__(self) -> None:
        self.execute_calls = 0

    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> SchemaSnapshot:
        del timeout_seconds
        assert allowed_schemas == ("public",)
        assert allowed_tables == ("public.film",)
        return _film_snapshot()

    def execute(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        del timeout_seconds
        assert sql
        self.execute_calls += 1
        return _film_result()

    def _consume_retry_count(self) -> int:
        return 0


class _CapturingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[LLMMessage, ...]] = []

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        assert timeout_seconds is not None
        self.calls.append(tuple(messages))
        return GenerationResult(
            output=GeneratedSQL(
                sql=(
                    "SELECT film_id, title, rental_rate "
                    "FROM film"
                )
            ),
            input_tokens=8,
            output_tokens=4,
            model="gold-isolation-stub",
            prompt_version="mvp-v1",
        )


class _RecordingSink:
    def __init__(self) -> None:
        self.records: list[TraceRecord] = []

    def emit(self, record: TraceRecord) -> None:
        self.records.append(record)


def _execute_successfully(
    case: EvaluationCase,
) -> tuple[tuple[LLMMessage, ...], ...]:
    connector = _SuccessfulConnector()
    provider = _CapturingProvider()
    sink = _RecordingSink()

    evaluation = evaluate_case(
        case,
        connector=connector,
        model_routing=single_provider_test_routing(provider),
        trace_sink=sink,
    )

    assert evaluation.passed is True
    assert evaluation.gold_validation_passed is True
    assert evaluation.gold_executed is True
    assert evaluation.prediction_validation_passed is True
    assert evaluation.prediction_execute_count == 1
    assert evaluation.comparison is not None
    assert evaluation.comparison.passed is True
    assert connector.execute_calls == 2
    assert len(provider.calls) >= 1
    assert len(sink.records) == 1
    return tuple(provider.calls)


def _all_mapping_keys(value: object) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _all_mapping_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_mapping_keys(item)


def _message_bytes(
    calls: tuple[tuple[LLMMessage, ...], ...],
) -> bytes:
    return b"\x1e".join(
        message.role.encode("ascii")
        + b"\x00"
        + message.content.encode("utf-8")
        for call in calls
        for message in call
    )


def _gold_execute_case() -> EvaluationCase:
    cases = load_case_suite(_GOLD_CASES_PATH).cases
    case = cases[0]
    assert case.case_id == "PG-MVP-001"
    return case


def test_successful_gold_execute_prompt_has_a_closed_runtime_only_schema() -> None:
    case = _gold_execute_case()

    calls = _execute_successfully(case)

    assert len(calls) == 1
    assert tuple(message.role for message in calls[0]) == (
        "system",
        "user",
    )
    payload = json.loads(calls[0][1].content)
    assert isinstance(payload, dict)
    assert frozenset(payload) == _USER_PAYLOAD_KEYS
    assert payload["question"] == case.question
    assert payload["candidate_tables"]
    assert all(
        frozenset(candidate) == _CANDIDATE_TABLE_KEYS
        for candidate in payload["candidate_tables"]
    )
    assert payload["candidate_fields"]
    assert all(
        frozenset(candidate) == _CANDIDATE_FIELD_KEYS
        for candidate in payload["candidate_fields"]
    )
    assert {
        candidate["object_id"]
        for candidate in payload["candidate_tables"]
    } == {"public.film"}
    assert {
        candidate["object_id"]
        for candidate in payload["candidate_fields"]
    } == {
        "public.film.film_id",
        "public.film.rental_rate",
        "public.film.title",
    }
    assert payload["primary_keys"] == []
    assert payload["foreign_keys"] == []
    assert payload["join_paths"] == []
    assert (
        _FORBIDDEN_EVALUATION_KEYS
        & set(_all_mapping_keys(payload))
    ) == set()
    assert case.gold_sql not in _message_bytes(calls).decode("utf-8")


def test_gold_postprocessing_labels_cannot_change_provider_bytes() -> None:
    case = _gold_execute_case()
    changed_payload = case.model_dump()
    changed_payload["tags"] = (
        "postprocessing-only",
        "must-not-enter-provider",
    )
    changed_payload["difficulty"] = Difficulty.COMPLEX
    relabeled_case = EvaluationCase.model_validate(changed_payload)

    original_calls = _execute_successfully(case)
    relabeled_calls = _execute_successfully(relabeled_case)

    assert _message_bytes(relabeled_calls) == _message_bytes(original_calls)


def _production_isolation_violations(
    app_root: Path,
) -> tuple[str, ...]:
    def static_string(
        node: ast.AST,
        bindings: dict[str, ast.AST],
        *,
        seen: frozenset[str] = frozenset(),
    ) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = static_string(node.left, bindings, seen=seen)
            right = static_string(node.right, bindings, seen=seen)
            if left is not None and right is not None:
                return left + right
        if isinstance(node, ast.Name) and node.id not in seen:
            bound = bindings.get(node.id)
            if bound is not None:
                return static_string(
                    bound,
                    bindings,
                    seen=seen | {node.id},
                )
        return None

    def static_path_parts(
        node: ast.AST,
        bindings: dict[str, ast.AST],
        *,
        seen: frozenset[str] = frozenset(),
    ) -> Iterable[str]:
        rendered = static_string(node, bindings, seen=seen)
        if rendered is not None:
            yield rendered
            return
        if isinstance(node, ast.Name) and node.id not in seen:
            bound = bindings.get(node.id)
            if bound is not None:
                yield from static_path_parts(
                    bound,
                    bindings,
                    seen=seen | {node.id},
                )
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            yield from static_path_parts(node.left, bindings, seen=seen)
            yield from static_path_parts(node.right, bindings, seen=seen)
        elif isinstance(node, ast.Call):
            for argument in node.args:
                yield from static_path_parts(
                    argument,
                    bindings,
                    seen=seen,
                )
            for keyword in node.keywords:
                yield from static_path_parts(
                    keyword.value,
                    bindings,
                    seen=seen,
                )
        elif isinstance(node, ast.Attribute):
            yield from static_path_parts(node.value, bindings, seen=seen)

    def is_protected_path(value: str) -> bool:
        normalized = value.replace("\\", "/")
        return (
            normalized == "evaluation"
            or normalized.startswith("evaluation/")
            or any(
                dataset_name in normalized
                for dataset_name in _PROTECTED_DATASET_NAMES
            )
        )

    violations: list[str] = []
    for source_path in sorted(app_root.rglob("*.py")):
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_path))
        relative_path = source_path.relative_to(app_root.parent)
        bindings: dict[str, ast.AST] = {}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                bindings[node.targets[0].id] = node.value
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.value is not None
            ):
                bindings[node.target.id] = node.value
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots = {
                    alias.name.partition(".")[0]
                    for alias in node.names
                }
                if "evaluation" in imported_roots:
                    violations.append(
                        f"{relative_path}: imports evaluation"
                    )
            elif isinstance(node, ast.ImportFrom):
                imported_root = (node.module or "").partition(".")[0]
                if imported_root == "evaluation":
                    violations.append(
                        f"{relative_path}: imports evaluation"
                    )
            elif isinstance(node, ast.Call):
                call_name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else (
                        node.func.attr
                        if isinstance(node.func, ast.Attribute)
                        else ""
                    )
                )
                if call_name in {"__import__", "import_module"} and node.args:
                    imported_name = static_string(node.args[0], bindings)
                    if (
                        imported_name is not None
                        and imported_name.partition(".")[0] == "evaluation"
                    ):
                        violations.append(
                            f"{relative_path}: imports evaluation"
                        )
                if call_name not in {
                    "open",
                    "read_bytes",
                    "read_text",
                    "readlines",
                }:
                    continue
                path_nodes: tuple[ast.AST, ...]
                if (
                    isinstance(node.func, ast.Attribute)
                    and call_name != "open"
                ):
                    path_nodes = (node.func.value,)
                else:
                    path_nodes = tuple(node.args) + tuple(
                        keyword.value
                        for keyword in node.keywords
                        if keyword.arg in {None, "file"}
                    )
                if any(
                    is_protected_path(part)
                    for path_node in path_nodes
                    for part in static_path_parts(path_node, bindings)
                ):
                    violations.append(
                        f"{relative_path}: references protected "
                        "evaluation data"
                    )
    return tuple(violations)


def test_static_gate_rejects_constructed_evaluation_access(
    tmp_path: Path,
) -> None:
    app_root = tmp_path / "app"
    app_root.mkdir()
    (app_root / "contaminated.py").write_text(
        """\
from pathlib import Path

__import__("eval" + "uation.runner")
Path(
    "ev" + "aluation",
    "cases",
    "retrieval_routing_" + "development.jsonl",
).read_bytes()
""",
        encoding="utf-8",
    )

    violations = _production_isolation_violations(app_root)

    assert len(violations) == 2
    assert any("imports evaluation" in item for item in violations)
    assert any(
        "references protected evaluation data" in item
        for item in violations
    )


def test_production_app_has_no_evaluation_import_or_dataset_read_path() -> None:
    app_root = _REPOSITORY_ROOT / "app"

    assert _production_isolation_violations(app_root) == ()


def test_production_package_configuration_excludes_evaluation() -> None:
    with (_REPOSITORY_ROOT / "pyproject.toml").open("rb") as stream:
        pyproject = tomllib.load(stream)
    package_find = pyproject["tool"]["setuptools"]["packages"]["find"]
    includes = tuple(package_find.get("include", ("*",)))
    excludes = tuple(package_find.get("exclude", ()))

    def included(package: str) -> bool:
        return (
            any(fnmatchcase(package, pattern) for pattern in includes)
            and not any(
                fnmatchcase(package, pattern)
                for pattern in excludes
            )
        )

    assert included("app") is True
    assert included("evaluation") is False
