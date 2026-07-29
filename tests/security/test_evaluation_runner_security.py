from collections.abc import Sequence
from pathlib import Path

from app.connectors.metadata import (
    ColumnMetadata,
    SchemaSnapshot,
    TableMetadata,
    build_schema_snapshot,
)
from app.connectors.models import ExecutionResult
from app.generation import (
    GenerationResult,
    GeneratedSQL,
    LLMMessage,
)
from app.observability import TraceRecord
from evaluation import load_case_suite
from evaluation.runner import evaluate_case

CASES = load_case_suite(
    Path("evaluation/cases/pagila_mvp.jsonl")
).cases


def _snapshot() -> SchemaSnapshot:
    return build_schema_snapshot(
        tables=(
            TableMetadata(
                schema_name="public",
                table_name="film",
                relation_kind="table",
                comment=None,
                columns=(
                    ColumnMetadata(
                        schema_name="public",
                        table_name="film",
                        column_name="film_id",
                        ordinal_position=1,
                        data_type="int4",
                        formatted_type="integer",
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


class SecurityConnector:
    def __init__(self, *, fail_execute: bool = False) -> None:
        self.fail_execute = fail_execute
        self.execute_calls = 0

    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
    ) -> SchemaSnapshot:
        del allowed_schemas, allowed_tables
        return _snapshot()

    def execute(self, sql: str) -> ExecutionResult:
        del sql
        self.execute_calls += 1
        if self.fail_execute:
            raise RuntimeError(
                "postgresql://reader:secret@db/pagila full prompt"
            )
        raise AssertionError("unexpected execution")

    def _consume_retry_count(self) -> int:
        return 0


class RecordingProvider:
    def __init__(self, sql: str) -> None:
        self.sql = sql
        self.calls: list[tuple[LLMMessage, ...]] = []

    def generate(
        self,
        messages: Sequence[LLMMessage],
    ) -> GenerationResult:
        self.calls.append(tuple(messages))
        return GenerationResult(
            output=GeneratedSQL(sql=self.sql),
            input_tokens=1,
            output_tokens=1,
            model="security-stub",
            prompt_version="mvp-v1",
        )


class RecordingSink:
    def __init__(self) -> None:
        self.record: TraceRecord | None = None

    def emit(self, record: TraceRecord) -> None:
        self.record = record


def test_gold_sql_and_expected_metadata_never_enter_model_messages() -> None:
    case = CASES[0]
    provider = RecordingProvider(
        "SELECT film_id FROM film"
    )
    connector = SecurityConnector(fail_execute=True)

    evaluation = evaluate_case(
        case,
        connector=connector,
        provider=provider,
        trace_sink=RecordingSink(),
    )

    assert evaluation.passed is False
    assert provider.calls == []
    rendered = evaluation.model_dump_json()
    assert case.question not in rendered
    assert case.gold_sql not in rendered
    assert "postgresql://" not in rendered
    assert "secret" not in rendered
    assert "full prompt" not in rendered


def test_dangerous_case_report_contains_no_fixture_sql() -> None:
    case = CASES[16]
    sink = RecordingSink()
    evaluation = evaluate_case(
        case,
        connector=SecurityConnector(),
        provider=RecordingProvider("SELECT film_id FROM film"),
        trace_sink=sink,
    )

    rendered = evaluation.model_dump_json()
    assert case.fixture["model_sql"] not in rendered
    assert case.question not in rendered
    assert "DROP TABLE" not in rendered
    assert evaluation.prediction_execute_count == 0
    assert sink.record is not None
    assert sink.record.generations[0].effective_contract_version == (
        "evaluation-fixture-v1"
    )
