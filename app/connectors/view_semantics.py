from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)
from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.connectors.metadata import (
    ColumnMetadata,
    SchemaSnapshot,
    TableMetadata,
    build_schema_snapshot,
)
from app.connectors.models import ExecutionResult

EXTRACTOR_VERSION = "view-semantic-extractor-v2"
POLICY_VERSION = "view-semantic-policy-v1"
_CANDIDATE_LEDGER_VERSION = "view-semantic-candidates-v1"
_REVIEW_VERSION = "view-semantic-review-v1"
_MANIFEST_VERSION = "view-semantics-v2"
_SAFE_ALIAS = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
_SENSITIVE_PARTS = frozenset(
    {
        "api_key",
        "credential",
        "password",
        "private",
        "secret",
        "token",
    }
)


class SemanticRule(str, Enum):
    DIRECT_PROJECTION_ALIAS = "direct_projection_alias_v1"
    SIMPLE_BOOLEAN_CASE_LABEL = "simple_boolean_case_label_v1"


class SemanticPolarity(str, Enum):
    NONE = "none"
    TRUE = "true"
    FALSE = "false"


@dataclass(frozen=True, slots=True)
class ViewDefinitionInput:
    schema_name: str
    view_name: str = field(repr=False)
    sql: str = field(repr=False)
    dependency_tables: tuple[str, ...] = field(
        default=(),
        repr=False,
    )

    def __post_init__(self) -> None:
        if (
            not self.schema_name.strip()
            or not self.view_name.strip()
            or not self.sql.strip()
            or any(
                "." not in table or not table.strip()
                for table in self.dependency_tables
            )
        ):
            raise ValueError("view definition input is invalid")


class ViewSemanticCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    object_id: str = Field(
        pattern=r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*\."
        r"[a-z_][a-z0-9_]*$"
    )
    alias: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    rule: SemanticRule
    polarity: SemanticPolarity
    source_definition_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_polarity(self) -> Self:
        expected = (
            SemanticPolarity.NONE
            if self.rule is SemanticRule.DIRECT_PROJECTION_ALIAS
            else self.polarity
        )
        if (
            expected is not self.polarity
            or (
                self.rule
                is SemanticRule.SIMPLE_BOOLEAN_CASE_LABEL
                and self.polarity is SemanticPolarity.NONE
            )
        ):
            raise ValueError("view semantic candidate is invalid")
        return self


class ViewSemanticCandidateLedger(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ledger_version: str = _CANDIDATE_LEDGER_VERSION
    extractor_version: str = EXTRACTOR_VERSION
    policy_version: str = POLICY_VERSION
    database_schema_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    base_schema_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    allowed_scope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    view_definitions_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    candidates: tuple[ViewSemanticCandidate, ...]
    ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ViewSemanticReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved: bool
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ViewSemanticReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    review_version: str = _REVIEW_VERSION
    candidate_ledger_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    decisions: tuple[ViewSemanticReviewDecision, ...]
    review_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ViewSemanticEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    object_id: str = Field(
        pattern=r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*\."
        r"[a-z_][a-z0-9_]*$"
    )
    alias: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    rule: SemanticRule
    polarity: SemanticPolarity
    source_definition_set_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    approved_evidence_set_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    approved_review_set_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )


class ViewSemanticManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_version: str = _MANIFEST_VERSION
    extractor_version: str = EXTRACTOR_VERSION
    policy_version: str = POLICY_VERSION
    datasource_id: str = Field(min_length=1)
    database_schema_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    base_schema_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    enriched_schema_version: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    allowed_scope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    view_definitions_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    candidate_ledger_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    review_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    entries: tuple[ViewSemanticEntry, ...]


def _canonical_json(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(domain: bytes, value: object) -> str:
    payload = _canonical_json(value)
    framed = (
        len(domain).to_bytes(4, "big")
        + domain
        + len(payload).to_bytes(8, "big")
        + payload
    )
    return hashlib.sha256(framed).hexdigest()


def _source_digest(definition: ViewDefinitionInput) -> str:
    return _digest(
        b"view-definition-v1",
        {
            "schema_name": definition.schema_name,
            "view_name": definition.view_name,
            "sql": definition.sql,
            "dependency_tables": sorted(
                definition.dependency_tables
            ),
        },
    )


def _view_set_digest(
    definitions: Sequence[ViewDefinitionInput],
) -> str:
    records = sorted(
        (
            definition.schema_name,
            definition.view_name,
            definition.sql,
            tuple(sorted(definition.dependency_tables)),
        )
        for definition in definitions
    )
    return _digest(b"view-definition-set-v1", records)


def _scope_digest(
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
) -> str:
    return _digest(
        b"view-semantic-scope-v1",
        {
            "schemas": sorted(set(allowed_schemas)),
            "tables": sorted(set(allowed_tables)),
        },
    )


def _safe_alias(value: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    if (
        _SAFE_ALIAS.fullmatch(normalized) is None
        or any(part in normalized for part in _SENSITIVE_PARTS)
    ):
        return None
    return normalized


def _candidate(
    *,
    object_id: str,
    alias: str,
    rule: SemanticRule,
    polarity: SemanticPolarity,
    source_definition_sha256: str,
) -> ViewSemanticCandidate:
    fields = {
        "object_id": object_id,
        "alias": alias,
        "rule": rule.value,
        "polarity": polarity.value,
        "source_definition_sha256": source_definition_sha256,
    }
    return ViewSemanticCandidate(
        **fields,
        evidence_sha256=_digest(
            b"view-semantic-candidate-v1",
            fields,
        ),
    )


def _candidate_evidence(candidate: ViewSemanticCandidate) -> str:
    return _digest(
        b"view-semantic-candidate-v1",
        {
            "object_id": candidate.object_id,
            "alias": candidate.alias,
            "rule": candidate.rule.value,
            "polarity": candidate.polarity.value,
            "source_definition_sha256": (
                candidate.source_definition_sha256
            ),
        },
    )


def _tables_by_id(
    snapshot: SchemaSnapshot,
    allowed_tables: tuple[str, ...],
) -> dict[str, TableMetadata]:
    allowed = set(allowed_tables)
    return {
        f"{table.schema_name}.{table.table_name}": table
        for table in snapshot.tables
        if f"{table.schema_name}.{table.table_name}" in allowed
    }


def _resolved_table_id(
    table: exp.Table,
    definition: ViewDefinitionInput,
    tables: dict[str, TableMetadata],
) -> str | None:
    if table.db:
        object_id = f"{table.db}.{table.name}"
        return object_id if object_id in tables else None
    matches = tuple(
        dependency
        for dependency in definition.dependency_tables
        if dependency.rsplit(".", 1)[-1] == table.name
        and dependency in tables
    )
    return matches[0] if len(matches) == 1 else None


def _column_id(
    column: exp.Column,
    aliases: dict[str, str],
    tables: dict[str, TableMetadata],
) -> str | None:
    if not column.table or column.table not in aliases:
        return None
    table_id = aliases[column.table]
    table = tables[table_id]
    if column.name not in {
        item.column_name for item in table.columns
    }:
        return None
    return f"{table_id}.{column.name}"


def _column_metadata(
    object_id: str,
    tables: dict[str, TableMetadata],
) -> ColumnMetadata:
    schema_name, table_name, column_name = object_id.split(".", 2)
    table = tables[f"{schema_name}.{table_name}"]
    return next(
        column
        for column in table.columns
        if column.column_name == column_name
    )


def _text_literal(value: exp.Expression | None) -> str | None:
    literal = value
    if isinstance(value, exp.Cast):
        target = value.args.get("to")
        if (
            not isinstance(target, exp.DataType)
            or target.this is not exp.DType.TEXT
        ):
            return None
        literal = value.this
    if not isinstance(literal, exp.Literal) or not literal.is_string:
        return None
    return str(literal.this)


def _is_empty_case_default(value: exp.Expression | None) -> bool:
    return (
        value is None
        or isinstance(value, exp.Null)
        or _text_literal(value) == ""
    )


def _boolean_condition(
    condition: exp.Expression,
    aliases: dict[str, str],
    tables: dict[str, TableMetadata],
) -> tuple[str, SemanticPolarity] | None:
    polarity = SemanticPolarity.TRUE
    column: exp.Column | None = None
    if isinstance(condition, exp.Column):
        column = condition
    elif isinstance(condition, exp.Is):
        left = condition.this
        right = condition.expression
        if isinstance(left, exp.Column) and isinstance(
            right,
            exp.Boolean,
        ):
            column = left
            polarity = (
                SemanticPolarity.TRUE
                if right.this is True
                else SemanticPolarity.FALSE
            )
    if column is None:
        return None
    object_id = _column_id(column, aliases, tables)
    if object_id is None:
        return None
    metadata = _column_metadata(object_id, tables)
    if (
        metadata.data_type.casefold() not in {"bool", "boolean"}
        and metadata.formatted_type.casefold()
        not in {"bool", "boolean"}
    ):
        return None
    return object_id, polarity


def _case_candidate(
    expression: exp.Case,
    *,
    aliases: dict[str, str],
    tables: dict[str, TableMetadata],
    source_definition_sha256: str,
) -> ViewSemanticCandidate | None:
    ifs = tuple(expression.args.get("ifs") or ())
    if len(ifs) != 1 or not _is_empty_case_default(
        expression.args.get("default")
    ):
        return None
    branch = ifs[0]
    if not isinstance(branch, exp.If):
        return None
    condition = branch.this
    label_node = branch.args.get("true")
    if not isinstance(condition, exp.Expression):
        return None
    label = _text_literal(label_node)
    if label is None:
        return None
    resolved = _boolean_condition(condition, aliases, tables)
    alias = _safe_alias(label)
    if resolved is None or alias is None:
        return None
    object_id, polarity = resolved
    return _candidate(
        object_id=object_id,
        alias=alias,
        rule=SemanticRule.SIMPLE_BOOLEAN_CASE_LABEL,
        polarity=polarity,
        source_definition_sha256=source_definition_sha256,
    )


def _extract_definition(
    definition: ViewDefinitionInput,
    *,
    tables: dict[str, TableMetadata],
    allowed_schemas: set[str],
) -> tuple[ViewSemanticCandidate, ...]:
    if definition.schema_name not in allowed_schemas:
        return ()
    try:
        statements = parse(definition.sql, read="postgres")
    except ParseError:
        return ()
    if len(statements) != 1 or not isinstance(
        statements[0],
        exp.Select,
    ):
        return ()
    statement = statements[0]
    if (
        any(True for _ in statement.find_all(exp.Star))
        or any(True for _ in statement.find_all(exp.Subquery))
        or statement.args.get("with_") is not None
        or any(
            nested is not statement
            for nested in statement.find_all(exp.Select)
        )
    ):
        return ()

    table_aliases: dict[str, str] = {}
    referenced_tables: set[str] = set()
    for table in statement.find_all(exp.Table):
        object_id = _resolved_table_id(table, definition, tables)
        alias = table.alias_or_name
        if (
            object_id is None
            or not alias
            or (
                alias in table_aliases
                and table_aliases[alias] != object_id
            )
        ):
            return ()
        table_aliases[alias] = object_id
        referenced_tables.add(object_id)
    if not referenced_tables:
        return ()
    if definition.dependency_tables and referenced_tables != set(
        definition.dependency_tables
    ):
        return ()

    for column in statement.find_all(exp.Column):
        if _column_id(column, table_aliases, tables) is None:
            return ()

    source_sha256 = _source_digest(definition)
    candidates: list[ViewSemanticCandidate] = []
    for projection in statement.expressions:
        if not isinstance(projection, exp.Alias):
            continue
        output_alias = _safe_alias(projection.alias)
        if isinstance(projection.this, exp.Column):
            object_id = _column_id(
                projection.this,
                table_aliases,
                tables,
            )
            if (
                object_id is not None
                and output_alias is not None
                and output_alias != projection.this.name.casefold()
            ):
                candidates.append(
                    _candidate(
                        object_id=object_id,
                        alias=output_alias,
                        rule=(
                            SemanticRule.DIRECT_PROJECTION_ALIAS
                        ),
                        polarity=SemanticPolarity.NONE,
                        source_definition_sha256=source_sha256,
                    )
                )
        elif isinstance(projection.this, exp.Case):
            item = _case_candidate(
                projection.this,
                aliases=table_aliases,
                tables=tables,
                source_definition_sha256=source_sha256,
            )
            if item is not None:
                candidates.append(item)
    return tuple(candidates)


def extract_view_semantic_candidates(
    definitions: Sequence[ViewDefinitionInput],
    *,
    snapshot: SchemaSnapshot,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
    database_schema_sha256: str,
) -> ViewSemanticCandidateLedger:
    if (
        re.fullmatch(r"[0-9a-f]{64}", database_schema_sha256)
        is None
        or not allowed_schemas
        or not allowed_tables
    ):
        raise ValueError("view semantic extraction input is invalid")
    tables = _tables_by_id(snapshot, allowed_tables)
    candidates = tuple(
        candidate
        for definition in definitions
        for candidate in _extract_definition(
            definition,
            tables=tables,
            allowed_schemas=set(allowed_schemas),
        )
    )
    aliases_to_objects: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        aliases_to_objects[candidate.alias].add(
            candidate.object_id
        )
    filtered = tuple(
        sorted(
            (
                candidate
                for candidate in candidates
                if len(
                    aliases_to_objects[candidate.alias]
                )
                == 1
            ),
            key=lambda item: (
                item.object_id,
                item.alias,
                item.rule.value,
                item.polarity.value,
                item.source_definition_sha256,
            ),
        )
    )
    fields = {
        "ledger_version": _CANDIDATE_LEDGER_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "policy_version": POLICY_VERSION,
        "database_schema_sha256": database_schema_sha256,
        "base_schema_version": snapshot.schema_version,
        "allowed_scope_sha256": _scope_digest(
            allowed_schemas,
            allowed_tables,
        ),
        "view_definitions_sha256": _view_set_digest(definitions),
        "candidates": filtered,
    }
    return ViewSemanticCandidateLedger(
        **fields,
        ledger_sha256=_digest(
            b"view-semantic-ledger-v1",
            {
                **fields,
                "candidates": [
                    item.model_dump(mode="json")
                    for item in filtered
                ],
            },
        ),
    )


def validate_view_semantic_candidate_ledger(
    ledger: ViewSemanticCandidateLedger,
) -> None:
    fields = {
        "ledger_version": ledger.ledger_version,
        "extractor_version": ledger.extractor_version,
        "policy_version": ledger.policy_version,
        "database_schema_sha256": ledger.database_schema_sha256,
        "base_schema_version": ledger.base_schema_version,
        "allowed_scope_sha256": ledger.allowed_scope_sha256,
        "view_definitions_sha256": (
            ledger.view_definitions_sha256
        ),
        "candidates": [
            item.model_dump(mode="json")
            for item in ledger.candidates
        ],
    }
    if (
        ledger.ledger_version != _CANDIDATE_LEDGER_VERSION
        or ledger.extractor_version != EXTRACTOR_VERSION
        or ledger.policy_version != POLICY_VERSION
        or len(
            {
                candidate.evidence_sha256
                for candidate in ledger.candidates
            }
        )
        != len(ledger.candidates)
        or any(
            candidate.evidence_sha256
            != _candidate_evidence(candidate)
            for candidate in ledger.candidates
        )
        or ledger.ledger_sha256
        != _digest(b"view-semantic-ledger-v1", fields)
    ):
        raise ValueError("view semantic candidate ledger is invalid")


def review_semantic_candidate(
    candidate: ViewSemanticCandidate,
    *,
    approved: bool,
) -> ViewSemanticReviewDecision:
    fields = {
        "evidence_sha256": candidate.evidence_sha256,
        "approved": approved,
    }
    return ViewSemanticReviewDecision(
        **fields,
        review_sha256=_digest(
            b"view-semantic-review-decision-v1",
            fields,
        ),
    )


def _valid_review_decision(
    decision: ViewSemanticReviewDecision,
) -> bool:
    return decision.review_sha256 == _digest(
        b"view-semantic-review-decision-v1",
        {
            "evidence_sha256": decision.evidence_sha256,
            "approved": decision.approved,
        },
    )


def build_view_semantic_review(
    ledger: ViewSemanticCandidateLedger,
    decisions: Sequence[ViewSemanticReviewDecision],
    *,
    require_complete: bool = True,
) -> ViewSemanticReview:
    validate_view_semantic_candidate_ledger(ledger)
    items = tuple(
        sorted(decisions, key=lambda item: item.evidence_sha256)
    )
    expected = {
        candidate.evidence_sha256
        for candidate in ledger.candidates
    }
    actual = {decision.evidence_sha256 for decision in items}
    if (
        len(items) != len(actual)
        or not actual <= expected
        or (require_complete and actual != expected)
        or any(
            not _valid_review_decision(decision)
            for decision in items
        )
    ):
        raise ValueError("view semantic review is invalid")
    fields = {
        "review_version": _REVIEW_VERSION,
        "candidate_ledger_sha256": ledger.ledger_sha256,
        "decisions": items,
    }
    return ViewSemanticReview(
        **fields,
        review_file_sha256=_digest(
            b"view-semantic-review-file-v1",
            {
                **fields,
                "decisions": [
                    item.model_dump(mode="json")
                    for item in items
                ],
            },
        ),
    )


def validate_view_semantic_review(
    ledger: ViewSemanticCandidateLedger,
    review: ViewSemanticReview,
    *,
    require_complete: bool,
) -> None:
    validate_view_semantic_candidate_ledger(ledger)
    expected = {
        candidate.evidence_sha256
        for candidate in ledger.candidates
    }
    actual = {
        decision.evidence_sha256
        for decision in review.decisions
    }
    fields = {
        "review_version": review.review_version,
        "candidate_ledger_sha256": (
            review.candidate_ledger_sha256
        ),
        "decisions": [
            item.model_dump(mode="json")
            for item in review.decisions
        ],
    }
    if (
        review.review_version != _REVIEW_VERSION
        or review.candidate_ledger_sha256
        != ledger.ledger_sha256
        or len(actual) != len(review.decisions)
        or not actual <= expected
        or (require_complete and actual != expected)
        or any(
            not _valid_review_decision(decision)
            for decision in review.decisions
        )
        or review.review_file_sha256
        != _digest(b"view-semantic-review-file-v1", fields)
    ):
        raise ValueError("view semantic review is invalid")


def _enrich_with_entries(
    snapshot: SchemaSnapshot,
    entries: Sequence[ViewSemanticEntry],
) -> SchemaSnapshot:
    aliases_by_object: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        aliases_by_object[entry.object_id].add(entry.alias)
    tables = tuple(
        replace(
            table,
            columns=tuple(
                replace(
                    column,
                    aliases=tuple(
                        sorted(
                            {
                                *column.aliases,
                                *aliases_by_object.get(
                                    (
                                        f"{column.schema_name}."
                                        f"{column.table_name}."
                                        f"{column.column_name}"
                                    ),
                                    set(),
                                ),
                            }
                        )
                    ),
                )
                for column in table.columns
            ),
        )
        for table in snapshot.tables
    )
    return build_schema_snapshot(
        tables=tables,
        primary_keys=snapshot.primary_keys,
        foreign_keys=snapshot.foreign_keys,
        unique_constraints=snapshot.unique_constraints,
        unique_indexes=snapshot.unique_indexes,
    )


def _approved_entries(
    ledger: ViewSemanticCandidateLedger,
    review: ViewSemanticReview,
) -> tuple[ViewSemanticEntry, ...]:
    validate_view_semantic_review(
        ledger,
        review,
        require_complete=True,
    )
    candidates = {
        candidate.evidence_sha256: candidate
        for candidate in ledger.candidates
    }
    decisions = {
        decision.evidence_sha256: decision
        for decision in review.decisions
    }
    if (
        review.candidate_ledger_sha256 != ledger.ledger_sha256
        or set(decisions) != set(candidates)
        or any(
            not _valid_review_decision(decision)
            for decision in review.decisions
        )
    ):
        raise ValueError("view semantic review is invalid")
    approved_by_semantic: dict[
        tuple[str, str, SemanticRule, SemanticPolarity],
        list[ViewSemanticCandidate],
    ] = defaultdict(list)
    for candidate in ledger.candidates:
        if decisions[candidate.evidence_sha256].approved:
            approved_by_semantic[
                (
                    candidate.object_id,
                    candidate.alias,
                    candidate.rule,
                    candidate.polarity,
                )
            ].append(candidate)
    return tuple(
        ViewSemanticEntry(
            object_id=object_id,
            alias=alias,
            rule=rule,
            polarity=polarity,
            source_definition_set_sha256=_digest(
                b"view-semantic-source-definition-set-v1",
                sorted(
                    {
                        candidate.source_definition_sha256
                        for candidate in grouped
                    }
                ),
            ),
            approved_evidence_set_sha256=_digest(
                b"view-semantic-approved-evidence-set-v1",
                sorted(
                    candidate.evidence_sha256
                    for candidate in grouped
                ),
            ),
            approved_review_set_sha256=_digest(
                b"view-semantic-approved-review-set-v1",
                sorted(
                    decisions[
                        candidate.evidence_sha256
                    ].review_sha256
                    for candidate in grouped
                ),
            ),
        )
        for (
            object_id,
            alias,
            rule,
            polarity,
        ), grouped in sorted(
            approved_by_semantic.items(),
            key=lambda item: (
                item[0][0],
                item[0][1],
                item[0][2].value,
                item[0][3].value,
            ),
        )
    )


def validate_view_semantic_audit_bundle(
    ledger: ViewSemanticCandidateLedger,
    review: ViewSemanticReview,
    manifest: ViewSemanticManifest,
) -> None:
    try:
        entries = _approved_entries(ledger, review)
    except ValueError:
        raise ValueError(
            "view semantic audit bundle is invalid"
        ) from None
    if (
        manifest.manifest_version != _MANIFEST_VERSION
        or manifest.extractor_version != ledger.extractor_version
        or manifest.policy_version != ledger.policy_version
        or manifest.database_schema_sha256
        != ledger.database_schema_sha256
        or manifest.base_schema_version != ledger.base_schema_version
        or manifest.allowed_scope_sha256
        != ledger.allowed_scope_sha256
        or manifest.view_definitions_sha256
        != ledger.view_definitions_sha256
        or manifest.candidate_ledger_sha256 != ledger.ledger_sha256
        or manifest.review_file_sha256 != review.review_file_sha256
        or manifest.entries != entries
    ):
        raise ValueError("view semantic audit bundle is invalid")


def build_view_semantic_manifest(
    ledger: ViewSemanticCandidateLedger,
    review: ViewSemanticReview,
    *,
    snapshot: SchemaSnapshot,
    datasource_id: str,
) -> ViewSemanticManifest:
    if snapshot.schema_version != ledger.base_schema_version:
        raise ValueError("view semantic review is invalid")
    entries = _approved_entries(ledger, review)
    enriched = _enrich_with_entries(snapshot, entries)
    manifest = ViewSemanticManifest(
        datasource_id=datasource_id,
        database_schema_sha256=ledger.database_schema_sha256,
        base_schema_version=ledger.base_schema_version,
        enriched_schema_version=enriched.schema_version,
        allowed_scope_sha256=ledger.allowed_scope_sha256,
        view_definitions_sha256=(
            ledger.view_definitions_sha256
        ),
        candidate_ledger_sha256=ledger.ledger_sha256,
        review_file_sha256=review.review_file_sha256,
        entries=entries,
    )
    validate_view_semantic_audit_bundle(ledger, review, manifest)
    return manifest


def enrich_schema_snapshot(
    snapshot: SchemaSnapshot,
    manifest: ViewSemanticManifest,
) -> SchemaSnapshot:
    return _enrich_with_entries(snapshot, manifest.entries)


def validate_view_semantic_manifest(
    manifest: ViewSemanticManifest,
    *,
    snapshot: SchemaSnapshot,
    datasource_id: str,
    database_schema_sha256: str,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
) -> None:
    if (
        manifest.manifest_version != _MANIFEST_VERSION
        or manifest.extractor_version != EXTRACTOR_VERSION
        or manifest.policy_version != POLICY_VERSION
        or manifest.datasource_id != datasource_id
        or manifest.database_schema_sha256
        != database_schema_sha256
        or manifest.base_schema_version != snapshot.schema_version
        or manifest.allowed_scope_sha256
        != _scope_digest(allowed_schemas, allowed_tables)
        or len(
            {
                (
                    entry.object_id,
                    entry.alias,
                    entry.rule,
                    entry.polarity,
                )
                for entry in manifest.entries
            }
        )
        != len(manifest.entries)
    ):
        raise ValueError("view semantic manifest is invalid")
    authorized_object_ids = {
        (
            f"{column.schema_name}.{column.table_name}."
            f"{column.column_name}"
        )
        for table in snapshot.tables
        if table.schema_name in set(allowed_schemas)
        and f"{table.schema_name}.{table.table_name}"
        in set(allowed_tables)
        for column in table.columns
    }
    aliases_to_objects: dict[str, set[str]] = defaultdict(set)
    for entry in manifest.entries:
        aliases_to_objects[entry.alias].add(entry.object_id)
        if (
            entry.object_id not in authorized_object_ids
            or _safe_alias(entry.alias) != entry.alias
            or
            (
                entry.rule is SemanticRule.DIRECT_PROJECTION_ALIAS
                and entry.polarity is not SemanticPolarity.NONE
            )
            or (
                entry.rule
                is SemanticRule.SIMPLE_BOOLEAN_CASE_LABEL
                and entry.polarity is SemanticPolarity.NONE
            )
        ):
            raise ValueError("view semantic manifest is invalid")
    if any(
        len(object_ids) != 1
        for object_ids in aliases_to_objects.values()
    ):
        raise ValueError("view semantic manifest is invalid")
    enriched = _enrich_with_entries(snapshot, manifest.entries)
    if enriched.schema_version != manifest.enriched_schema_version:
        raise ValueError("view semantic manifest is invalid")


def load_view_semantic_manifest(
    path: Path,
    *,
    expected_sha256: str,
    snapshot: SchemaSnapshot,
    datasource_id: str,
    database_schema_sha256: str,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
) -> ViewSemanticManifest:
    try:
        payload = path.read_bytes()
        if (
            re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
            is None
            or hashlib.sha256(payload).hexdigest()
            != expected_sha256
        ):
            raise ValueError
        manifest = ViewSemanticManifest.model_validate_json(payload)
        validate_view_semantic_manifest(
            manifest,
            snapshot=snapshot,
            datasource_id=datasource_id,
            database_schema_sha256=database_schema_sha256,
            allowed_schemas=allowed_schemas,
            allowed_tables=allowed_tables,
        )
        return manifest
    except (
        OSError,
        ValidationError,
        ValueError,
    ):
        raise ValueError(
            "view semantic manifest is invalid"
        ) from None


@dataclass(frozen=True, slots=True)
class FrozenSemanticConnector:
    _delegate: object = field(repr=False)
    manifest: ViewSemanticManifest

    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> SchemaSnapshot:
        reader = getattr(self._delegate, "read_metadata", None)
        if not callable(reader):
            raise ValueError("semantic connector is invalid")
        snapshot = (
            reader(allowed_schemas, allowed_tables)
            if timeout_seconds is None
            else reader(
                allowed_schemas,
                allowed_tables,
                timeout_seconds=timeout_seconds,
            )
        )
        if not isinstance(snapshot, SchemaSnapshot):
            raise ValueError("semantic connector is invalid")
        requested_schemas = set(allowed_schemas)
        requested_tables = set(allowed_tables)
        returned_tables = {
            f"{table.schema_name}.{table.table_name}"
            for table in snapshot.tables
        }
        if (
            any(
                table.schema_name not in requested_schemas
                for table in snapshot.tables
            )
            or not returned_tables <= requested_tables
        ):
            raise ValueError("semantic connector is invalid")
        object_ids = {
            (
                f"{column.schema_name}.{column.table_name}."
                f"{column.column_name}"
            )
            for table in snapshot.tables
            for column in table.columns
        }
        entries = tuple(
            entry
            for entry in self.manifest.entries
            if entry.object_id in object_ids
            and _safe_alias(entry.alias) == entry.alias
        )
        return _enrich_with_entries(snapshot, entries)

    def execute(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        executor = getattr(self._delegate, "execute", None)
        if not callable(executor):
            raise ValueError("semantic connector is invalid")
        result = (
            executor(sql)
            if timeout_seconds is None
            else executor(
                sql,
                timeout_seconds=timeout_seconds,
            )
        )
        if not isinstance(result, ExecutionResult):
            raise ValueError("semantic connector is invalid")
        return result

    def _consume_retry_count(self) -> int:
        consume = getattr(
            self._delegate,
            "_consume_retry_count",
            None,
        )
        if not callable(consume):
            return 0
        value = consume()
        return value if type(value) is int and value >= 0 else 0

    @contextmanager
    def read_only_snapshot(
        self,
    ) -> Iterator[FrozenSemanticConnector]:
        factory = getattr(
            self._delegate,
            "read_only_snapshot",
            None,
        )
        if not callable(factory):
            yield self
            return
        with factory() as snapshot_delegate:
            yield FrozenSemanticConnector(
                snapshot_delegate,
                self.manifest,
            )
