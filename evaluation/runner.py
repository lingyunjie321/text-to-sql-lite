from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from pydantic import BaseModel

from app.connectors.errors import ErrorType
from app.connectors.metadata import SchemaSnapshot
from app.connectors.models import ExecutionResult
from app.generation import (
    GenerationResult,
    GeneratedSQL,
    LLMMessage,
    LLMProvider,
)
from app.observability import (
    TraceRecord,
    TraceSink,
    TracedWorkflowRunner,
)
from app.workflow import (
    SQLTaskState,
    WorkflowContext,
    new_task_state,
    run_workflow,
)
from app.validation import validate_sql
from evaluation.comparator import compare_results
from evaluation.models import (
    CaseEvidence,
    CaseEvaluation,
    ComparisonResult,
    EvaluationCase,
    ExpectedBehavior,
)

EVIDENCE_VERSION = "stage10-evidence-v3"
_FIXTURE_PROMPT_VERSION = "evaluation-fixture-v1"


class EvaluationConnector(Protocol):
    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
    ) -> SchemaSnapshot: ...

    def execute(self, sql: str) -> ExecutionResult: ...


@dataclass(slots=True)
class _CountingConnector:
    connector: EvaluationConnector
    execute_count: int = 0
    metadata_snapshot: SchemaSnapshot | None = None

    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
    ) -> SchemaSnapshot:
        if self.metadata_snapshot is not None:
            return self.metadata_snapshot
        self.metadata_snapshot = self.connector.read_metadata(
            allowed_schemas,
            allowed_tables,
        )
        return self.metadata_snapshot

    def execute(self, sql: str) -> ExecutionResult:
        self.execute_count += 1
        return self.connector.execute(sql)

    def _consume_retry_count(self) -> int:
        consume = getattr(
            self.connector,
            "_consume_retry_count",
            None,
        )
        if not callable(consume):
            return 0
        count = consume()
        return count if type(count) is int and count >= 0 else 0


class _CaseProvider:
    def __init__(
        self,
        case: EvaluationCase,
        delegate: LLMProvider,
    ) -> None:
        self._case = case
        self._delegate = delegate
        self._call_count = 0

    def _fixture_sql(self) -> str | None:
        fixture_key = None
        if self._case.category.value == "dangerous_sql":
            fixture_key = "model_sql"
        elif self._case.category.value == "permission":
            unauthorized_tables = tuple(
                table
                for table in self._case.gold_tables
                if table not in self._case.allowed_tables
            )
            if (
                len(unauthorized_tables) == 1
                and re.fullmatch(
                    r"[a-z_][a-z0-9_]*",
                    unauthorized_tables[0],
                )
            ):
                return (
                    f'SELECT 1 FROM "{unauthorized_tables[0]}"'
                )
        elif (
            self._case.category.value == "reflection"
            and self._call_count == 0
        ):
            fixture_key = "initial_model_sql"
        value = (
            self._case.fixture.get(fixture_key)
            if fixture_key is not None
            else None
        )
        return value if isinstance(value, str) and value.strip() else None

    def generate(
        self,
        messages: Sequence[LLMMessage],
    ) -> GenerationResult:
        fixture_sql = self._fixture_sql()
        self._call_count += 1
        if fixture_sql is None:
            return self._delegate.generate(messages)
        return GenerationResult(
            output=GeneratedSQL(sql=fixture_sql),
            input_tokens=0,
            output_tokens=0,
            model="evaluation-fixture",
            prompt_version=_FIXTURE_PROMPT_VERSION,
        )


class _EvidenceSink:
    def __init__(self, delegate: TraceSink) -> None:
        self._delegate = delegate
        self.record: TraceRecord | None = None
        self.sha256: str | None = None

    def emit(self, record: TraceRecord) -> None:
        self._delegate.emit(record)
        payload = record.model_dump_json().encode("utf-8")
        self.record = record
        self.sha256 = hashlib.sha256(payload).hexdigest()


def _qualified_tables(case: EvaluationCase) -> tuple[str, ...]:
    return tuple(
        sorted(f"public.{table}" for table in case.allowed_tables)
    )


def _gold_table_reference(value: str) -> str:
    return value.removeprefix("public.")


def _gold_field_reference(value: str) -> str:
    return value.removeprefix("public.")


def _canonical(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {
            str(key): _canonical(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def case_evidence_sha256(
    evidence: CaseEvaluation | dict[str, object],
) -> str:
    if isinstance(evidence, CaseEvaluation):
        source: object = evidence.model_dump(
            exclude={
                "evidence_sha256",
                "audit_status",
                "review_evidence_sha256",
            }
        )
    else:
        source = evidence
    fields = CaseEvidence.model_validate(source).model_dump(mode="json")
    payload = json.dumps(
        _canonical(fields),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(
        EVIDENCE_VERSION.encode("ascii") + b"\0" + payload
    ).hexdigest()


def review_evidence_sha256(evidence_sha256: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", evidence_sha256) is None:
        raise ValueError("evaluation evidence digest is invalid")
    return hashlib.sha256(
        b"stage10-review-v3\0" + evidence_sha256.encode("ascii")
    ).hexdigest()


def _evaluation(
    case: EvaluationCase,
    *,
    evaluation_baseline_id: str,
    code: str,
    actual_state: SQLTaskState | None = None,
    gold_validation_passed: bool = False,
    gold_executed: bool = False,
    prediction_execute_count: int = 0,
    comparison: ComparisonResult | None = None,
    table_recall_passed: bool = False,
    field_recall_passed: bool = False,
    join_recall_passed: bool = False,
    trace_sha256: str | None = None,
) -> CaseEvaluation:
    execution = (
        actual_state.execution_result
        if actual_state is not None
        else None
    )
    fields: dict[str, object] = {
        "case_id": case.case_id,
        "evaluation_baseline_id": evaluation_baseline_id,
        "initial_status": case.status,
        "expected_behavior": case.expected_behavior,
        "expected_final_status": case.expected_final_status,
        "actual_final_status": (
            actual_state.final_status
            if actual_state is not None
            else None
        ),
        "expected_error_type": case.expected_error_type,
        "actual_error_type": (
            actual_state.error_type
            if actual_state is not None
            else None
        ),
        "gold_validation_passed": gold_validation_passed,
        "gold_executed": gold_executed,
        "prediction_validation_passed": (
            actual_state is not None
            and actual_state.validation_result is not None
            and actual_state.validation_result.is_valid
        ),
        "prediction_execute_count": prediction_execute_count,
        "comparison": comparison,
        "table_recall_passed": table_recall_passed,
        "field_recall_passed": field_recall_passed,
        "join_recall_passed": join_recall_passed,
        "attempt_count": (
            len(actual_state.sql_attempts)
            if actual_state is not None
            else 0
        ),
        "repair_count": (
            actual_state.repair_count
            if actual_state is not None
            else 0
        ),
        "trace_sha256": trace_sha256,
        "input_tokens": (
            actual_state.token_usage.input_tokens
            if actual_state is not None
            else 0
        ),
        "output_tokens": (
            actual_state.token_usage.output_tokens
            if actual_state is not None
            else 0
        ),
        "workflow_duration_ms": (
            sum(
                timing.duration_ms
                for timing in actual_state.node_timings
            )
            if actual_state is not None
            else 0
        ),
        "database_duration_ms": (
            execution.execution_time_ms
            if execution is not None
            else 0
        ),
        "passed": code == "EVALUATION_PASS",
        "code": code,
    }
    return CaseEvaluation(
        **fields,
        evidence_sha256=case_evidence_sha256(fields),
    )


def _normalized_join_edge(edge: str) -> tuple[str, str] | None:
    if edge.count("=") != 1:
        return None
    left, right = edge.split("=", 1)

    def normalize(value: str) -> str:
        stripped = value.strip()
        return (
            stripped.removeprefix("public.")
            if stripped.count(".") >= 2
            else stripped
        )

    left = normalize(left)
    right = normalize(right)
    if not left or not right:
        return None
    return tuple(sorted((left, right)))  # type: ignore[return-value]


def _join_recall(state: SQLTaskState, case: EvaluationCase) -> bool:
    expected = {
        normalized
        for edge in case.gold_join_edges
        if (normalized := _normalized_join_edge(edge)) is not None
    }
    observed: set[tuple[str, str]] = set()
    for path in state.join_paths:
        for edge in path.edges:
            for source, target in zip(
                edge.source_columns,
                edge.target_columns,
                strict=True,
            ):
                normalized = _normalized_join_edge(
                    f"{edge.source_table}.{source}="
                    f"{edge.target_table}.{target}"
                )
                if normalized is not None:
                    observed.add(normalized)
    return expected <= observed


def _result_code(
    case: EvaluationCase,
    state: SQLTaskState,
    *,
    gold_validation_passed: bool,
    gold_executed: bool,
    prediction_execute_count: int,
    comparison: ComparisonResult | None,
    table_recall_passed: bool,
    field_recall_passed: bool,
    trace_sha256: str | None,
) -> str:
    if trace_sha256 is None:
        return "EVALUATION_TRACE_MISSING"
    if state.final_status is not case.expected_final_status:
        return "EVALUATION_FINAL_STATUS_MISMATCH"
    if state.error_type is not case.expected_error_type:
        return "EVALUATION_ERROR_TYPE_MISMATCH"
    if case.expected_behavior is ExpectedBehavior.EXECUTE:
        if not gold_validation_passed:
            return "EVALUATION_GOLD_VALIDATION_FAILED"
        if not gold_executed:
            return "EVALUATION_GOLD_EXECUTION_FAILED"
        if not table_recall_passed:
            return "EVALUATION_TABLE_RECALL_FAILED"
        if not field_recall_passed:
            return "EVALUATION_FIELD_RECALL_FAILED"
        if (
            state.validation_result is None
            or not state.validation_result.is_valid
        ):
            return "EVALUATION_PREDICTION_VALIDATION_FAILED"
        expected_execute_count = sum(
            attempt.execution_result is not None
            or attempt.database_error is not None
            for attempt in state.sql_attempts
        )
        if (
            state.execution_result is None
            or prediction_execute_count != expected_execute_count
        ):
            return "EVALUATION_PREDICTION_EXECUTION_FAILED"
        if comparison is None:
            return "EVALUATION_COMPARISON_MISSING"
        if not comparison.passed:
            return comparison.code
    elif prediction_execute_count != 0:
        return "EVALUATION_SECURITY_EXECUTION_OCCURRED"
    elif (
        case.expected_behavior is ExpectedBehavior.REJECT
        and state.repair_count != 0
    ):
        return "EVALUATION_SECURITY_REPAIR_OCCURRED"
    return "EVALUATION_PASS"


def _evaluate_case_in_snapshot(
    case: EvaluationCase,
    *,
    evaluation_baseline_id: str,
    connector: EvaluationConnector,
    provider: LLMProvider,
    trace_sink: TraceSink,
) -> CaseEvaluation:
    allowed_tables = _qualified_tables(case)
    gold_validation_passed = False
    gold_executed = False
    gold_result: ExecutionResult | None = None
    shared_snapshot: SchemaSnapshot | None = None
    try:
        if case.expected_behavior is ExpectedBehavior.EXECUTE:
            shared_snapshot = connector.read_metadata(
                ("public",),
                allowed_tables,
            )
            validation = validate_sql(
                case.gold_sql,
                allowed_schemas=("public",),
                allowed_tables=allowed_tables,
                snapshot=shared_snapshot,
            )
            gold_validation_passed = validation.is_valid
            if not validation.is_valid or validation.normalized_sql is None:
                return _evaluation(
                    case,
                    evaluation_baseline_id=evaluation_baseline_id,
                    code="EVALUATION_GOLD_VALIDATION_FAILED",
                )
            gold_result = connector.execute(validation.normalized_sql)
            gold_executed = True
    except Exception:
        return _evaluation(
            case,
            evaluation_baseline_id=evaluation_baseline_id,
            code="EVALUATION_GOLD_EXECUTION_FAILED",
            gold_validation_passed=gold_validation_passed,
        )

    counted = _CountingConnector(
        connector,
        metadata_snapshot=shared_snapshot,
    )
    evidence_sink = _EvidenceSink(trace_sink)
    case_provider = _CaseProvider(case, provider)
    state = new_task_state(
        request_id=f"evaluation-{case.case_id.casefold()}",
        trace_id=f"trace-{case.case_id.casefold()}",
        question=case.question,
        datasource_id=case.datasource_id,
        requested_schemas=("public",),
    )
    try:
        terminal = TracedWorkflowRunner(
            run_workflow,
            evidence_sink,
        )(
            state,
            context=WorkflowContext(
                provider=case_provider,
                connector=counted,
                datasource_id="pagila",
                allowed_schemas=("public",),
                allowed_tables=allowed_tables,
            ),
        )
    except Exception:
        return _evaluation(
            case,
            evaluation_baseline_id=evaluation_baseline_id,
            code="EVALUATION_INTERNAL_ERROR",
            gold_validation_passed=gold_validation_passed,
            gold_executed=gold_executed,
            prediction_execute_count=counted.execute_count,
        )

    linked_tables = {
        table.table_name
        for table in terminal.candidate_tables
    }
    linked_fields = {
        f"{field.table_name}.{field.column_name}"
        for field in terminal.candidate_fields
    }
    final_validation = terminal.validation_result
    referenced_tables = (
        {
            _gold_table_reference(table)
            for table in final_validation.referenced_tables
        }
        if final_validation is not None
        else set()
    )
    referenced_fields = (
        {
            _gold_field_reference(field)
            for field in final_validation.referenced_columns
        }
        if final_validation is not None
        else set()
    )
    required_tables = set(case.gold_tables)
    required_fields = set(case.gold_fields)
    table_recall_passed = (
        required_tables <= linked_tables
        and required_tables <= referenced_tables
    )
    field_recall_passed = (
        required_fields <= linked_fields
        and required_fields <= referenced_fields
    )
    join_recall_passed = _join_recall(terminal, case)
    comparison = None
    if (
        case.expected_behavior is ExpectedBehavior.EXECUTE
        and terminal.execution_result is not None
        and gold_result is not None
    ):
        comparison = compare_results(
            terminal.execution_result,
            gold_result,
            mode=case.comparison_mode,
            order_sensitive=case.order_sensitive,
            numeric_tolerances=case.numeric_tolerances,
        )
    code = _result_code(
        case,
        terminal,
        gold_validation_passed=gold_validation_passed,
        gold_executed=gold_executed,
        prediction_execute_count=counted.execute_count,
        comparison=comparison,
        table_recall_passed=table_recall_passed,
        field_recall_passed=field_recall_passed,
        trace_sha256=evidence_sink.sha256,
    )
    return _evaluation(
        case,
        evaluation_baseline_id=evaluation_baseline_id,
        code=code,
        actual_state=terminal,
        gold_validation_passed=gold_validation_passed,
        gold_executed=gold_executed,
        prediction_execute_count=counted.execute_count,
        comparison=comparison,
        table_recall_passed=table_recall_passed,
        field_recall_passed=field_recall_passed,
        join_recall_passed=join_recall_passed,
        trace_sha256=evidence_sink.sha256,
    )


def evaluate_case(
    case: EvaluationCase,
    *,
    evaluation_baseline_id: str = "0" * 64,
    connector: EvaluationConnector,
    provider: LLMProvider,
    trace_sink: TraceSink,
) -> CaseEvaluation:
    snapshot_factory = getattr(
        connector,
        "read_only_snapshot",
        None,
    )
    if callable(snapshot_factory):
        with snapshot_factory() as snapshot_connector:
            return _evaluate_case_in_snapshot(
                case,
                evaluation_baseline_id=evaluation_baseline_id,
                connector=snapshot_connector,
                provider=provider,
                trace_sink=trace_sink,
            )
    return _evaluate_case_in_snapshot(
        case,
        evaluation_baseline_id=evaluation_baseline_id,
        connector=connector,
        provider=provider,
        trace_sink=trace_sink,
    )
