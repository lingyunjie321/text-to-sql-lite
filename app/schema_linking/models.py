from dataclasses import dataclass

TOP_K = 10


@dataclass(frozen=True, slots=True)
class CandidateTable:
    object_id: str
    schema_name: str
    table_name: str
    relation_kind: str
    comment: str | None
    score: float
    matched_tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateField:
    object_id: str
    schema_name: str
    table_name: str
    column_name: str
    formatted_type: str
    nullable: bool
    comment: str | None
    score: float
    matched_tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class JoinEdge:
    constraint_name: str
    source_table: str
    source_columns: tuple[str, ...]
    target_table: str
    target_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class JoinPath:
    tables: tuple[str, ...]
    edges: tuple[JoinEdge, ...]


@dataclass(frozen=True, slots=True)
class SchemaLinkingResult:
    candidate_tables: tuple[CandidateTable, ...]
    candidate_fields: tuple[CandidateField, ...]
    join_paths: tuple[JoinPath, ...]
    schema_version: str
