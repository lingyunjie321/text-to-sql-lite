from dataclasses import FrozenInstanceError, replace

import pytest

from app.connectors.metadata import (
    ColumnMetadata,
    ForeignKeyMetadata,
    MetadataScope,
    PrimaryKeyMetadata,
    TableMetadata,
    UniqueConstraintMetadata,
    UniqueIndexMetadata,
    build_schema_snapshot,
    empty_schema_snapshot,
    normalize_metadata_scope,
)


FILM_ID = ColumnMetadata(
    schema_name="public",
    table_name="film",
    column_name="film_id",
    ordinal_position=1,
    data_type="int4",
    formatted_type="integer",
    nullable=False,
    comment="Primary key",
)
FILM_LANGUAGE_ID = ColumnMetadata(
    schema_name="public",
    table_name="film",
    column_name="language_id",
    ordinal_position=2,
    data_type="int2",
    formatted_type="smallint",
    nullable=False,
    comment=None,
)
LANGUAGE_ID = ColumnMetadata(
    schema_name="public",
    table_name="language",
    column_name="language_id",
    ordinal_position=1,
    data_type="int4",
    formatted_type="integer",
    nullable=False,
    comment=None,
)
FILM = TableMetadata(
    schema_name="public",
    table_name="film",
    relation_kind="table",
    comment="Available films",
    columns=(FILM_LANGUAGE_ID, FILM_ID),
)
LANGUAGE = TableMetadata(
    schema_name="public",
    table_name="language",
    relation_kind="table",
    comment=None,
    columns=(LANGUAGE_ID,),
)
FILM_PK = PrimaryKeyMetadata(
    constraint_name="film_pkey",
    schema_name="public",
    table_name="film",
    columns=("film_id",),
)
FILM_LANGUAGE_FK = ForeignKeyMetadata(
    constraint_name="film_language_id_fkey",
    source_schema="public",
    source_table="film",
    source_columns=("language_id",),
    target_schema="public",
    target_table="language",
    target_columns=("language_id",),
)
FILM_TITLE_UNIQUE = UniqueConstraintMetadata(
    constraint_name="film_title_key",
    schema_name="public",
    table_name="film",
    columns=("film_id",),
)
FILM_UNIQUE_INDEX = UniqueIndexMetadata(
    index_name="idx_unq_film_id",
    schema_name="public",
    table_name="film",
    columns=("film_id",),
    definition="CREATE UNIQUE INDEX idx_unq_film_id ON public.film (film_id)",
    predicate=None,
)


def _snapshot(**overrides: object):
    values = {
        "tables": (FILM, LANGUAGE),
        "primary_keys": (FILM_PK,),
        "foreign_keys": (FILM_LANGUAGE_FK,),
        "unique_constraints": (FILM_TITLE_UNIQUE,),
        "unique_indexes": (FILM_UNIQUE_INDEX,),
    }
    values.update(overrides)
    return build_schema_snapshot(**values)


@pytest.mark.parametrize(
    "value",
    [
        FILM_ID,
        FILM,
        FILM_PK,
        FILM_LANGUAGE_FK,
        FILM_TITLE_UNIQUE,
        FILM_UNIQUE_INDEX,
        _snapshot(),
    ],
)
def test_metadata_models_are_immutable_and_use_tuples(value: object) -> None:
    with pytest.raises((FrozenInstanceError, AttributeError)):
        setattr(value, next(iter(value.__dataclass_fields__)), "changed")

    for field_name in value.__dataclass_fields__:
        field_value = getattr(value, field_name)
        if isinstance(field_value, (list, tuple)):
            assert isinstance(field_value, tuple)


def test_schema_snapshot_has_canonical_order() -> None:
    first = _snapshot(tables=(FILM, LANGUAGE))
    second = _snapshot(tables=(LANGUAGE, FILM))

    assert first == second
    assert [table.table_name for table in first.tables] == ["film", "language"]
    assert [column.column_name for column in first.tables[0].columns] == [
        "film_id",
        "language_id",
    ]
    assert first.schemas == ("public",)
    assert len(first.schema_version) == 64
    assert first.schema_version.isascii()
    assert first.schema_version.isalnum()
    assert first.schema_version == first.schema_version.lower()


@pytest.mark.parametrize(
    "overrides",
    [
        {"tables": (replace(FILM, comment="Changed"), LANGUAGE)},
        {
            "tables": (
                replace(
                    FILM,
                    columns=(replace(FILM_ID, data_type="int8"), FILM_LANGUAGE_ID),
                ),
                LANGUAGE,
            )
        },
        {
            "tables": (
                replace(
                    FILM,
                    columns=(replace(FILM_ID, nullable=True), FILM_LANGUAGE_ID),
                ),
                LANGUAGE,
            )
        },
        {"primary_keys": (replace(FILM_PK, columns=("language_id",)),)},
        {
            "foreign_keys": (
                replace(FILM_LANGUAGE_FK, target_table="film"),
            )
        },
        {
            "unique_indexes": (
                replace(FILM_UNIQUE_INDEX, definition="changed"),
            )
        },
        {
            "unique_indexes": (
                replace(FILM_UNIQUE_INDEX, predicate="film_id > 0"),
            )
        },
    ],
)
def test_schema_version_changes_with_semantic_metadata(
    overrides: dict[str, object],
) -> None:
    assert _snapshot(**overrides).schema_version != _snapshot().schema_version


def test_empty_snapshot_has_stable_literal_fingerprint() -> None:
    first = empty_schema_snapshot()
    second = empty_schema_snapshot()

    assert first == second
    assert first.schema_version == (
        "1df03ce977cb0b0e0385a833b9d97d29408c0f63c134d1a780dea68ddc1cc9b7"
    )


def test_scope_deduplicates_and_sorts_qualified_tables() -> None:
    scope = normalize_metadata_scope(
        ("public", "Public", "public"),
        (
            "public.language",
            "Public.Actor",
            "public.film",
            "public.film",
        ),
    )

    assert scope == MetadataScope(
        schemas=("Public", "public"),
        table_pairs=(
            ("Public", "Actor"),
            ("public", "film"),
            ("public", "language"),
        ),
    )
    assert scope.schema_parameters == ["Public", "public", "public"]
    assert scope.table_parameters == ["Actor", "film", "language"]
    assert scope.is_empty is False


@pytest.mark.parametrize(
    ("allowed_schemas", "allowed_tables"),
    [
        ((" ",), ("public.film",)),
        (("public",), (" ",)),
        (("public",), (".film",)),
        (("public",), ("public.",)),
    ],
)
def test_scope_rejects_empty_identifiers(
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
) -> None:
    with pytest.raises(
        ValueError, match="metadata scope contains an empty identifier"
    ):
        normalize_metadata_scope(allowed_schemas, allowed_tables)


def test_scope_rejects_unqualified_table() -> None:
    with pytest.raises(
        ValueError, match="allowed table must be schema-qualified"
    ):
        normalize_metadata_scope(("public",), ("film",))


def test_scope_filters_tables_outside_allowed_schemas() -> None:
    scope = normalize_metadata_scope(
        ("public",),
        ("other.film", "public.film"),
    )

    assert scope.table_pairs == (("public", "film"),)


@pytest.mark.parametrize(
    ("allowed_schemas", "allowed_tables"),
    [
        ((), ("public.film",)),
        (("public",), ()),
        ((), ()),
    ],
)
def test_scope_is_empty_when_either_input_is_empty(
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
) -> None:
    assert normalize_metadata_scope(
        allowed_schemas, allowed_tables
    ).is_empty
