from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from app.connectors.metadata import (
    ColumnMetadata,
    ForeignKeyMetadata,
    PrimaryKeyMetadata,
    SchemaSnapshot,
    TableMetadata,
    build_schema_snapshot,
)
from app.connectors.models import (
    ExecutionResult,
    ResultColumn,
)
from app.generation import (
    GenerationResult,
    GeneratedSQL,
    LLMMessage,
    ModelRoutingRuntime,
    build_single_provider_routing_runtime,
)
from app.generation.models import PROMPT_VERSION
from app.schema_linking import (
    EmbeddingIndexRegistry,
    RetrievalRuntime,
    authorize_schema_snapshot,
)
from evaluation.loader import (
    LoadedRetrievalRoutingSuite,
    load_retrieval_routing_suites,
)
from evaluation.models import Difficulty, RetrievalRoutingCase

_CASES_DIRECTORY = Path(__file__).resolve().parent / "cases"
_DEVELOPMENT_PATH = (
    _CASES_DIRECTORY / "retrieval_routing_development.jsonl"
)
_CALIBRATION_PATH = (
    _CASES_DIRECTORY / "retrieval_routing_calibration.jsonl"
)
_SYNTHETIC_EMBEDDING_VERSION = "stage1-synthetic-embedding-v1"
_SYNTHETIC_SEMANTIC_VERSION = "stage1-synthetic-semantics-v1"
_SYNTHETIC_MODEL_CONFIG_SHA256 = hashlib.sha256(
    b"stage1-synthetic-generation-v1"
).hexdigest()
_TABLE_ID = re.compile(
    r"^synthetic/rr(?:dev|cal)\.[a-z][a-z0-9_]*$"
)
_BM25_FIELD_HOLDOUT = (
    "synthetic/rrcal.solar_inverter.dc_voltage"
)


def _normalized_semantic_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


@lru_cache(maxsize=1)
def _all_cases() -> tuple[RetrievalRoutingCase, ...]:
    suites = load_retrieval_routing_suites(
        _DEVELOPMENT_PATH,
        _CALIBRATION_PATH,
    )
    return (*suites.development.cases, *suites.calibration.cases)


def _positive_table_ids(
    case: RetrievalRoutingCase,
) -> frozenset[str]:
    if case.expected_complexity is Difficulty.MEDIUM:
        return frozenset(case.expected_tables[:1])
    return frozenset(case.expected_tables)


@lru_cache(maxsize=1)
def _semantic_bindings() -> tuple[
    tuple[str, frozenset[str]], ...
]:
    return tuple(
        (
            case.question,
            frozenset(
                (
                    *positive_tables,
                    *(
                        field_id
                        for field_id in case.expected_fields
                        if field_id.rsplit(".", 1)[0]
                        in positive_tables
                    ),
                )
            ),
        )
        for case in _all_cases()
        for positive_tables in (_positive_table_ids(case),)
    )


def _local_table_name(table_id: str) -> tuple[str, str]:
    schema_name, separator, table_name = table_id.rpartition(".")
    if (
        not separator
        or not schema_name
        or not table_name
    ):
        raise ValueError("stage1 synthetic fixture is invalid")
    return schema_name, table_name


@lru_cache(maxsize=1)
def build_stage1_synthetic_snapshot() -> SchemaSnapshot:
    cases = _all_cases()
    table_ids = {
        table_id
        for case in cases
        for table_id in case.allowed_tables
    }
    fields_by_table: dict[str, set[str]] = {
        table_id: set() for table_id in table_ids
    }
    table_questions: dict[str, set[str]] = {
        table_id: set() for table_id in table_ids
    }
    field_questions: dict[str, set[str]] = {}
    foreign_keys: dict[
        tuple[str, str, str, str],
        ForeignKeyMetadata,
    ] = {}

    for case in cases:
        positive_tables = _positive_table_ids(case)
        for table_id in positive_tables:
            table_questions[table_id].add(case.question)
        for field_id in case.expected_fields:
            table_id, _, column_name = field_id.rpartition(".")
            fields_by_table[table_id].add(column_name)
            if (
                table_id in positive_tables
                and field_id != _BM25_FIELD_HOLDOUT
            ):
                field_questions.setdefault(field_id, set()).add(
                    case.question
                )
        for edge in case.expected_join_edges:
            left, right = edge.split("=", 1)
            source_table, _, source_column = left.rpartition(".")
            target_table, _, target_column = right.rpartition(".")
            source_schema, source_name = _local_table_name(
                source_table
            )
            target_schema, target_name = _local_table_name(
                target_table
            )
            key = (
                source_table,
                source_column,
                target_table,
                target_column,
            )
            foreign_keys[key] = ForeignKeyMetadata(
                constraint_name=(
                    f"fk_{source_name}_{source_column}_"
                    f"{target_name}_{target_column}"
                ),
                source_schema=source_schema,
                source_table=source_name,
                source_columns=(source_column,),
                target_schema=target_schema,
                target_table=target_name,
                target_columns=(target_column,),
            )

    tables: list[TableMetadata] = []
    primary_keys: list[PrimaryKeyMetadata] = []
    for table_id in sorted(table_ids):
        schema_name, table_name = _local_table_name(table_id)
        if not fields_by_table[table_id]:
            fields_by_table[table_id].add("record_key")
        column_names = tuple(sorted(fields_by_table[table_id]))
        primary_column = next(
            (
                column_name
                for column_name in column_names
                if column_name.endswith("_key")
            ),
            column_names[0],
        )
        columns = tuple(
            ColumnMetadata(
                schema_name=schema_name,
                table_name=table_name,
                column_name=column_name,
                ordinal_position=ordinal,
                data_type="text",
                formatted_type="text",
                nullable=column_name != primary_column,
                comment=(
                    f"Synthetic field {table_name}.{column_name}."
                ),
                aliases=tuple(
                    (
                        column_name.replace("_", " "),
                        *sorted(
                            field_questions.get(
                                f"{table_id}.{column_name}",
                                (),
                            )
                        ),
                    )
                ),
            )
            for ordinal, column_name in enumerate(
                column_names,
                start=1,
            )
        )
        tables.append(
            TableMetadata(
                schema_name=schema_name,
                table_name=table_name,
                relation_kind="table",
                comment=f"Synthetic table {table_name}.",
                columns=columns,
                aliases=tuple(
                    (
                        table_name.replace("_", " "),
                        *sorted(table_questions[table_id]),
                    )
                ),
            )
        )
        primary_keys.append(
            PrimaryKeyMetadata(
                constraint_name=f"pk_{table_name}",
                schema_name=schema_name,
                table_name=table_name,
                columns=(primary_column,),
            )
        )

    return build_schema_snapshot(
        tables=tuple(tables),
        primary_keys=tuple(primary_keys),
        foreign_keys=tuple(foreign_keys.values()),
        unique_constraints=(),
        unique_indexes=(),
    )


def validate_stage1_synthetic_suite(
    suite: LoadedRetrievalRoutingSuite,
) -> None:
    if not isinstance(suite, LoadedRetrievalRoutingSuite):
        raise ValueError("stage1 synthetic fixture is invalid")
    snapshot = build_stage1_synthetic_snapshot()
    table_ids = {
        f"{table.schema_name}.{table.table_name}"
        for table in snapshot.tables
    }
    field_ids = {
        (
            f"{table.schema_name}.{table.table_name}."
            f"{column.column_name}"
        )
        for table in snapshot.tables
        for column in table.columns
    }
    join_edges = {
        frozenset(
            (
                (
                    f"{key.source_schema}.{key.source_table}."
                    f"{source_column}"
                ),
                (
                    f"{key.target_schema}.{key.target_table}."
                    f"{target_column}"
                ),
            )
        )
        for key in snapshot.foreign_keys
        for source_column, target_column in zip(
            key.source_columns,
            key.target_columns,
            strict=True,
        )
    }
    if any(
        case.namespace != suite.namespace
        or not set(case.allowed_tables).issubset(table_ids)
        or not set(case.expected_fields).issubset(field_ids)
        or any(
            frozenset(edge.split("=", 1)) not in join_edges
            for edge in case.expected_join_edges
        )
        for case in suite.cases
    ):
        raise ValueError("stage1 synthetic fixture is invalid")


class Stage1SyntheticEmbeddingProvider:
    @property
    def model_id(self) -> str:
        return _SYNTHETIC_EMBEDDING_VERSION

    @property
    def dimension(self) -> int:
        return len(_semantic_bindings()) + 1

    @property
    def provider_config_sha256(self) -> str:
        return hashlib.sha256(
            _SYNTHETIC_EMBEDDING_VERSION.encode("utf-8")
        ).hexdigest()

    def embed(
        self,
        texts: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[tuple[float, ...], ...]:
        if (
            not isinstance(texts, Sequence)
            or isinstance(texts, (str, bytes))
            or not texts
            or any(
                not isinstance(text, str) or not text.strip()
                for text in texts
            )
            or (
                timeout_seconds is not None
                and (
                    type(timeout_seconds) not in (int, float)
                    or not math.isfinite(timeout_seconds)
                    or timeout_seconds <= 0
                )
            )
        ):
            raise ValueError("stage1 synthetic embedding is invalid")

        bindings = _semantic_bindings()
        vectors: list[tuple[float, ...]] = []
        for text in texts:
            normalized_text = _normalized_semantic_text(text)
            object_id: str | None = None
            try:
                payload = json.loads(text)
                if isinstance(payload, dict):
                    value = payload.get("object_id")
                    if isinstance(value, str):
                        object_id = value
            except (TypeError, ValueError):
                pass
            components = [0.0] * self.dimension
            matched = False
            for index, (question, object_ids) in enumerate(bindings):
                if (
                    normalized_text
                    == _normalized_semantic_text(question)
                    or object_id in object_ids
                ):
                    components[index] = 1.0
                    matched = True
            if not matched:
                components[-1] = 1.0
            vectors.append(tuple(components))
        return tuple(vectors)


class Stage1SyntheticGenerationProvider:
    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        if (
            not isinstance(messages, Sequence)
            or isinstance(messages, (str, bytes))
            or not messages
            or (
                timeout_seconds is not None
                and (
                    type(timeout_seconds) not in (int, float)
                    or not math.isfinite(timeout_seconds)
                    or timeout_seconds <= 0
                )
            )
        ):
            raise ValueError("stage1 synthetic generation is invalid")
        table_id = "synthetic/rrdev.weather_beacon"
        try:
            payload = json.loads(messages[-1].content)
            candidates = payload.get("candidate_tables", ())
            if (
                isinstance(candidates, list)
                and candidates
                and isinstance(candidates[0], dict)
                and isinstance(
                    candidates[0].get("object_id"),
                    str,
                )
            ):
                candidate = candidates[0]["object_id"]
                if _TABLE_ID.fullmatch(candidate):
                    table_id = candidate
        except (AttributeError, TypeError, ValueError):
            pass
        schema_name, table_name = _local_table_name(table_id)
        sql = (
            'SELECT 1 AS synthetic_value FROM '
            f'"{schema_name}"."{table_name}" LIMIT 1'
        )
        input_tokens = sum(
            max(1, len(message.content.encode("utf-8")) // 3)
            for message in messages
        )
        return GenerationResult(
            output=GeneratedSQL(sql=sql),
            input_tokens=input_tokens,
            output_tokens=max(1, len(sql.encode("utf-8")) // 3),
            model="stage1-synthetic-generation-v1",
            prompt_version=PROMPT_VERSION,
        )


class Stage1SyntheticConnector:
    def __init__(self) -> None:
        self._snapshot = build_stage1_synthetic_snapshot()

    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> SchemaSnapshot:
        del timeout_seconds
        return authorize_schema_snapshot(
            snapshot=self._snapshot,
            allowed_schemas=allowed_schemas,
            allowed_tables=allowed_tables,
        )

    def execute(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        del sql, timeout_seconds
        return ExecutionResult(
            columns=(
                ResultColumn(
                    name="synthetic_value",
                    type_oid=23,
                ),
            ),
            rows=[[1]],
            returned_row_count=1,
            truncated=False,
            execution_time_ms=0.0,
        )


def build_stage1_synthetic_retrieval_runtime() -> RetrievalRuntime:
    return RetrievalRuntime(
        provider=Stage1SyntheticEmbeddingProvider(),
        registry=EmbeddingIndexRegistry(),
        semantic_version=_SYNTHETIC_SEMANTIC_VERSION,
    )


def build_stage1_synthetic_model_routing_runtime(
) -> ModelRoutingRuntime:
    return build_single_provider_routing_runtime(
        provider=Stage1SyntheticGenerationProvider(),
        model_config_sha256_value=(
            _SYNTHETIC_MODEL_CONFIG_SHA256
        ),
        max_input_tokens=32_768,
        max_output_tokens=2_048,
        timeout_seconds=30,
        data_boundary_id="stage1-synthetic-boundary-v1",
        provider_key="stage1-synthetic-provider",
    )
