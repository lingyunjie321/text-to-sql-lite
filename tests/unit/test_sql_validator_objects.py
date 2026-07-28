import pytest

from app.connectors.errors import ErrorType
from app.connectors.metadata import (
    ColumnMetadata,
    SchemaSnapshot,
    TableMetadata,
    build_schema_snapshot,
    empty_schema_snapshot,
)
from app.validation import ValidationResult, validate_sql


def _table(
    schema_name: str,
    table_name: str,
    columns: tuple[str, ...],
) -> TableMetadata:
    return TableMetadata(
        schema_name=schema_name,
        table_name=table_name,
        relation_kind="table",
        comment=None,
        columns=tuple(
            ColumnMetadata(
                schema_name=schema_name,
                table_name=table_name,
                column_name=column_name,
                ordinal_position=position,
                data_type="text",
                formatted_type="text",
                nullable=False,
                comment=None,
            )
            for position, column_name in enumerate(columns, start=1)
        ),
    )


def _snapshot(*tables: TableMetadata) -> SchemaSnapshot:
    return build_schema_snapshot(
        tables=tables,
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )


FILM = _table(
    "public",
    "film",
    ("film_id", "title", "language_id"),
)
LANGUAGE = _table(
    "public",
    "language",
    ("language_id", "name"),
)
PUBLIC_SNAPSHOT = _snapshot(FILM, LANGUAGE)
FILM_SNAPSHOT = _snapshot(FILM)
CROSS_SCHEMA_SNAPSHOT = _snapshot(
    _table("public", "film", ("film_id",)),
    _table("archive", "film", ("film_id",)),
)
CORRELATED_SNAPSHOT = _snapshot(
    _table("public", "customer", ("customer_id",)),
    _table("public", "rental", ("customer_id",)),
)
CAMEL_SNAPSHOT = _snapshot(
    _table("public", "CamelCase", ("id",)),
)


def _validate(
    sql: str,
    *,
    allowed_schemas: tuple[str, ...] = ("public",),
    allowed_tables: tuple[str, ...] = (
        "public.film",
        "public.language",
    ),
    snapshot: SchemaSnapshot = PUBLIC_SNAPSHOT,
) -> ValidationResult:
    return validate_sql(
        sql,
        allowed_schemas=allowed_schemas,
        allowed_tables=allowed_tables,
        snapshot=snapshot,
    )


def test_resolves_one_unqualified_authorized_table() -> None:
    result = _validate(
        "SELECT f.film_id FROM film AS f",
        allowed_tables=("public.film",),
        snapshot=FILM_SNAPSHOT,
    )

    assert result.is_valid
    assert result.referenced_tables == ("public.film",)


@pytest.mark.parametrize(
    "sql",
    [
        (
            "WITH selected AS (SELECT film_id FROM film) "
            "SELECT film_id FROM selected"
        ),
        (
            "SELECT picked.film_id "
            "FROM (SELECT film_id FROM film) AS picked"
        ),
    ],
)
def test_derived_sources_are_not_checked_as_database_tables(
    sql: str,
) -> None:
    result = _validate(
        sql,
        allowed_tables=("public.film",),
        snapshot=FILM_SNAPSHOT,
    )

    assert result.is_valid
    assert result.referenced_tables == ("public.film",)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT staff_id FROM staff",
        "SELECT film_id FROM other.film",
        "SELECT film_id FROM catalog.public.film",
    ],
)
def test_rejects_sources_outside_authorization(sql: str) -> None:
    result = _validate(
        sql,
        allowed_tables=("public.film",),
        snapshot=FILM_SNAPSHOT,
    )

    assert result.issue is not None
    assert result.issue.error_type is ErrorType.PERMISSION_DENIED
    assert result.issue.code == "SQL_OBJECT_NOT_ALLOWED"


def test_requires_schema_for_ambiguous_authorized_table() -> None:
    result = _validate(
        "SELECT film_id FROM film",
        allowed_schemas=("archive", "public"),
        allowed_tables=("archive.film", "public.film"),
        snapshot=CROSS_SCHEMA_SNAPSHOT,
    )

    assert result.issue is not None
    assert result.issue.error_type is ErrorType.SCHEMA_ERROR
    assert result.issue.code == "SQL_OBJECT_AMBIGUOUS"


def test_accepts_explicit_schema_for_ambiguous_table_name() -> None:
    result = _validate(
        "SELECT film_id FROM archive.film",
        allowed_schemas=("archive", "public"),
        allowed_tables=("archive.film", "public.film"),
        snapshot=CROSS_SCHEMA_SNAPSHOT,
    )

    assert result.is_valid
    assert result.referenced_tables == ("archive.film",)


def test_reports_authorized_object_missing_from_snapshot() -> None:
    result = _validate(
        "SELECT id FROM missing",
        allowed_tables=("public.missing",),
        snapshot=empty_schema_snapshot(),
    )

    assert result.issue is not None
    assert result.issue.error_type is ErrorType.SCHEMA_ERROR
    assert result.issue.code == "SQL_OBJECT_UNKNOWN"


def test_rejects_snapshot_that_exceeds_authorization() -> None:
    result = _validate(
        "SELECT film_id FROM film",
        allowed_tables=("public.film",),
        snapshot=PUBLIC_SNAPSHOT,
    )

    assert result.issue is not None
    assert result.issue.error_type is ErrorType.UNKNOWN
    assert result.issue.code == "SQL_VALIDATION_CONTEXT_INVALID"
    assert "film" not in result.issue.public_message.lower()


def test_quoted_case_sensitive_table_must_match_exactly() -> None:
    allowed = ("public.CamelCase",)
    accepted = _validate(
        'SELECT id FROM "public"."CamelCase"',
        allowed_tables=allowed,
        snapshot=CAMEL_SNAPSHOT,
    )
    rejected = _validate(
        "SELECT id FROM public.CamelCase",
        allowed_tables=allowed,
        snapshot=CAMEL_SNAPSHOT,
    )

    assert accepted.is_valid
    assert accepted.referenced_tables == ("public.CamelCase",)
    assert rejected.issue is not None
    assert rejected.issue.code == "SQL_OBJECT_NOT_ALLOWED"


def test_validates_and_reports_single_table_columns() -> None:
    result = _validate(
        "SELECT film_id, title FROM film",
        allowed_tables=("public.film",),
        snapshot=FILM_SNAPSHOT,
    )

    assert result.is_valid
    assert result.referenced_columns == (
        "public.film.film_id",
        "public.film.title",
    )


def test_validates_join_columns_and_aliases() -> None:
    result = _validate(
        "SELECT f.film_id, l.name "
        "FROM film AS f "
        "JOIN language AS l ON l.language_id = f.language_id"
    )

    assert result.is_valid
    assert result.referenced_tables == (
        "public.film",
        "public.language",
    )
    assert result.referenced_columns == (
        "public.film.film_id",
        "public.film.language_id",
        "public.language.language_id",
        "public.language.name",
    )


@pytest.mark.parametrize(
    "sql",
    [
        (
            "WITH selected AS (SELECT film_id FROM film) "
            "SELECT film_id FROM selected"
        ),
        (
            "SELECT picked.film_id "
            "FROM (SELECT film_id FROM film) AS picked"
        ),
    ],
)
def test_reports_only_base_columns_for_derived_sources(sql: str) -> None:
    result = _validate(
        sql,
        allowed_tables=("public.film",),
        snapshot=FILM_SNAPSHOT,
    )

    assert result.is_valid
    assert result.referenced_columns == ("public.film.film_id",)


def test_validates_correlated_outer_reference() -> None:
    result = _validate(
        "SELECT c.customer_id "
        "FROM customer AS c "
        "WHERE NOT EXISTS ("
        "SELECT 1 FROM rental AS r "
        "WHERE r.customer_id = c.customer_id"
        ")",
        allowed_tables=("public.customer", "public.rental"),
        snapshot=CORRELATED_SNAPSHOT,
    )

    assert result.is_valid
    assert result.referenced_columns == (
        "public.customer.customer_id",
        "public.rental.customer_id",
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT film.film_name FROM film",
        "SELECT film_name FROM film",
        (
            "SELECT language_id FROM film "
            "JOIN language ON film.language_id = language.language_id"
        ),
        (
            "WITH selected AS (SELECT film_id FROM film) "
            "SELECT title FROM selected"
        ),
        (
            "SELECT picked.title "
            "FROM (SELECT film_id FROM film) AS picked"
        ),
    ],
)
def test_rejects_unknown_or_ambiguous_columns(sql: str) -> None:
    result = _validate(sql)

    assert result.issue is not None
    assert result.issue.error_type is ErrorType.SCHEMA_ERROR
    assert result.issue.code == "SQL_COLUMN_INVALID"
    for identifier in ("film_name", "language_id", "title"):
        assert identifier not in result.issue.public_message.lower()
