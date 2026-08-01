from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path

from app.connectors.metadata import (
    ColumnMetadata,
    SchemaSnapshot,
    TableMetadata,
    build_schema_snapshot,
)
from app.connectors.errors import (
    DatabaseError,
    ErrorType,
    PostgreSQLConnectorError,
)
from app.connectors.models import ExecutionResult, ResultColumn
from app.generation import (
    GenerationResult,
    GeneratedSQL,
    LLMMessage,
)
from app.observability import TraceRecord
from app.schema_linking import (
    EmbeddingIndexRegistry,
    RetrievalRuntime,
)
from app.workflow import FinalStatus
from evaluation import load_case_suite
import evaluation.runner as evaluation_runner
from evaluation.runner import evaluate_case
from tests.routing_support import single_provider_test_routing

CASES = load_case_suite(
    Path("evaluation/cases/pagila_mvp_all_draft.jsonl")
).cases


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


def _film_id_title_result() -> ExecutionResult:
    return ExecutionResult(
        columns=(
            ResultColumn(name="film_id", type_oid=23),
            ResultColumn(name="title", type_oid=25),
        ),
        rows=[[1, "ACADEMY DINOSAUR"]],
        returned_row_count=1,
        truncated=False,
        execution_time_ms=1.0,
    )


class QueueConnector:
    def __init__(self, results: list[ExecutionResult]) -> None:
        self.results = results
        self.metadata_calls = 0
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
        self.metadata_calls += 1
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
        return self.results.pop(0)

    def _consume_retry_count(self) -> int:
        return 0


class SnapshotQueueConnector(QueueConnector):
    def __init__(self, results: list[ExecutionResult]) -> None:
        super().__init__(results)
        self.snapshot_entries = 0

    @contextmanager
    def read_only_snapshot(self):
        self.snapshot_entries += 1
        yield self


class FailFirstPredictionExecutionConnector(QueueConnector):
    def execute(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        del timeout_seconds
        assert sql
        self.execute_calls += 1
        if self.execute_calls == 2:
            raise PostgreSQLConnectorError(
                DatabaseError(
                    sqlstate="42703",
                    error_type=ErrorType.SCHEMA_ERROR,
                    code="DB_SCHEMA_ERROR",
                    retryable=False,
                    public_message=(
                        "The database operation failed."
                    ),
                )
            )
        return self.results.pop(0)


class ScriptedProvider:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls: list[tuple[LLMMessage, ...]] = []

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        del timeout_seconds
        self.calls.append(tuple(messages))
        return GenerationResult(
            output=GeneratedSQL(sql=self.outputs.pop(0)),
            input_tokens=8,
            output_tokens=4,
            model="runner-stub",
            prompt_version="mvp-v1",
        )


class RecordingSink:
    def __init__(self) -> None:
        self.records: list[TraceRecord] = []

    def emit(self, record: TraceRecord) -> None:
        self.records.append(record)


class DeterministicEmbeddingProvider:
    model_id = "evaluation-embedding-stub"
    dimension = 2
    provider_config_sha256 = "b" * 64

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def embed(
        self,
        texts: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[tuple[float, ...], ...]:
        del timeout_seconds
        self.calls.append(tuple(texts))
        return tuple((1.0, 0.0) for _ in texts)


def test_execute_case_validates_executes_and_compares_gold_result() -> None:
    case = CASES[0]
    connector = QueueConnector([_film_result(), _film_result()])
    provider = ScriptedProvider(
        ["SELECT film_id, title, rental_rate FROM film"]
    )
    sink = RecordingSink()

    evaluation = evaluate_case(
        case,
        connector=connector,
        model_routing=single_provider_test_routing(
            provider
        ),
        trace_sink=sink,
    )

    assert evaluation.passed is True
    assert evaluation.code == "EVALUATION_PASS"
    assert evaluation.actual_final_status is FinalStatus.SUCCEEDED_FIRST_PASS
    assert evaluation.gold_validation_passed is True
    assert evaluation.gold_executed is True
    assert evaluation.prediction_execute_count == 1
    assert evaluation.comparison is not None
    assert evaluation.comparison.passed is True
    assert evaluation.table_recall_passed is True
    assert evaluation.field_recall_passed is True
    assert evaluation.attempt_count == 1
    assert evaluation.repair_count == 0
    assert evaluation.trace_sha256 is not None
    assert len(sink.records) == 1
    assert connector.execute_calls == 2


def test_execute_case_injects_hybrid_retrieval_through_snapshot() -> None:
    connector = SnapshotQueueConnector(
        [_film_result(), _film_result()]
    )
    provider = DeterministicEmbeddingProvider()
    sink = RecordingSink()

    evaluation = evaluate_case(
        CASES[0],
        connector=connector,
        model_routing=single_provider_test_routing(
            ScriptedProvider(
                ["SELECT film_id, title, rental_rate FROM film"]
            )
        ),
        retrieval_runtime=RetrievalRuntime(
            provider=provider,
            registry=EmbeddingIndexRegistry(),
            semantic_version="evaluation-semantic-v1",
        ),
        trace_sink=sink,
    )

    assert evaluation.passed is True
    assert connector.snapshot_entries == 1
    assert len(provider.calls) == 2
    assert sink.records[0].retrieval is not None
    assert sink.records[0].retrieval.mode == "hybrid"


def test_execute_case_reuses_one_schema_and_transaction_snapshot() -> None:
    connector = SnapshotQueueConnector(
        [_film_result(), _film_result()]
    )

    evaluation = evaluate_case(
        CASES[0],
        connector=connector,
        model_routing=single_provider_test_routing(
            ScriptedProvider(
                ["SELECT film_id, title, rental_rate FROM film"]
            )
        ),
        trace_sink=RecordingSink(),
    )

    assert evaluation.passed is True
    assert connector.snapshot_entries == 1
    assert connector.metadata_calls == 1


def test_result_mismatch_fails_without_changing_execution_status() -> None:
    case = CASES[0]
    predicted = ExecutionResult(
        columns=_film_result().columns,
        rows=[[2, "WRONG", "0.99"]],
        returned_row_count=1,
        truncated=False,
        execution_time_ms=1.0,
    )

    evaluation = evaluate_case(
        case,
        connector=QueueConnector([_film_result(), predicted]),
        model_routing=single_provider_test_routing(
            ScriptedProvider(
                ["SELECT film_id, title, rental_rate FROM film"]
            )
        ),
        trace_sink=RecordingSink(),
    )

    assert evaluation.passed is False
    assert evaluation.code == "COMPARATOR_ROW_MISMATCH"
    assert evaluation.actual_final_status is FinalStatus.SUCCEEDED_FIRST_PASS


def test_final_sql_must_reference_every_required_gold_field() -> None:
    evaluation = evaluate_case(
        CASES[0],
        connector=QueueConnector(
            [_film_result(), _film_result()]
        ),
        model_routing=single_provider_test_routing(
            ScriptedProvider(
                [
                    (
                        "SELECT film_id, title, "
                        "0.99 AS rental_rate FROM film"
                    )
                ]
            )
        ),
        trace_sink=RecordingSink(),
    )

    assert evaluation.passed is False
    assert evaluation.field_recall_passed is False
    assert evaluation.code == "EVALUATION_FIELD_RECALL_FAILED"


def test_repaired_database_failure_counts_both_execution_attempts() -> None:
    case = CASES[0].model_copy(
        update={
            "expected_final_status": FinalStatus.SUCCEEDED_REPAIRED,
        }
    )
    connector = FailFirstPredictionExecutionConnector(
        [_film_result(), _film_result()]
    )

    evaluation = evaluate_case(
        case,
        connector=connector,
        model_routing=single_provider_test_routing(
            ScriptedProvider(
                [
                    (
                        "SELECT film_id, title, rental_rate FROM film "
                        "WHERE film_id > 0"
                    ),
                    "SELECT film_id, title, rental_rate FROM film",
                ]
            )
        ),
        trace_sink=RecordingSink(),
    )

    assert evaluation.actual_final_status is FinalStatus.SUCCEEDED_REPAIRED
    assert evaluation.prediction_execute_count == 2
    assert evaluation.attempt_count == 2
    assert evaluation.repair_count == 1
    assert evaluation.passed is True


def test_gold_match_does_not_require_linker_join_path_recall(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        evaluation_runner,
        "_join_recall",
        lambda state, case: False,
    )

    evaluation = evaluate_case(
        CASES[0],
        connector=QueueConnector([_film_result(), _film_result()]),
        model_routing=single_provider_test_routing(
            ScriptedProvider(
                ["SELECT film_id, title, rental_rate FROM film"]
            )
        ),
        trace_sink=RecordingSink(),
    )

    assert evaluation.join_recall_passed is False
    assert evaluation.passed is True


def test_dangerous_fixture_is_rejected_with_zero_prediction_execution() -> None:
    case = CASES[15]
    connector = QueueConnector([])
    provider = ScriptedProvider(["SELECT film_id FROM film"])

    evaluation = evaluate_case(
        case,
        connector=connector,
        model_routing=single_provider_test_routing(
            provider
        ),
        trace_sink=RecordingSink(),
    )

    assert evaluation.passed is True
    assert evaluation.actual_final_status is FinalStatus.REJECTED_SECURITY
    assert evaluation.prediction_execute_count == 0
    assert evaluation.repair_count == 0
    assert connector.execute_calls == 0
    assert provider.calls == []


def test_permission_case_uses_a_fixed_unauthorized_fixture() -> None:
    case = CASES[14]
    connector = QueueConnector([])
    provider = ScriptedProvider(["SELECT staff_id FROM staff"])

    evaluation = evaluate_case(
        case,
        connector=connector,
        model_routing=single_provider_test_routing(
            provider
        ),
        trace_sink=RecordingSink(),
    )

    assert evaluation.passed is True
    assert evaluation.actual_final_status is FinalStatus.REJECTED_SECURITY
    assert evaluation.prediction_execute_count == 0
    assert evaluation.repair_count == 0
    assert connector.execute_calls == 0
    assert provider.calls == []


def test_reflection_fixture_uses_real_provider_only_for_repair() -> None:
    case = CASES[17]
    connector = QueueConnector(
        [_film_id_title_result(), _film_id_title_result()]
    )
    provider = ScriptedProvider(
        ["SELECT film_id, title FROM film"]
    )

    evaluation = evaluate_case(
        case,
        connector=connector,
        model_routing=single_provider_test_routing(
            provider
        ),
        trace_sink=RecordingSink(),
    )

    assert evaluation.passed is True
    assert evaluation.actual_final_status is FinalStatus.SUCCEEDED_REPAIRED
    assert evaluation.attempt_count == 2
    assert evaluation.repair_count == 1
    assert len(provider.calls) == 1
    assert connector.execute_calls == 2
