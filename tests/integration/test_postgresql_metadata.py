import re

import pytest

from app.connectors.metadata import empty_schema_snapshot
from app.connectors.postgresql import PostgreSQLConnector


@pytest.mark.integration
def test_reads_authorized_film_columns(
    connector: PostgreSQLConnector,
) -> None:
    snapshot = connector.read_metadata(
        ("public",),
        ("public.film",),
    )

    assert snapshot.schemas == ("public",)
    assert [table.table_name for table in snapshot.tables] == ["film"]
    film = snapshot.tables[0]
    assert film.relation_kind == "table"
    assert [column.column_name for column in film.columns[:4]] == [
        "film_id",
        "title",
        "description",
        "release_year",
    ]
    assert film.columns[0].data_type == "int4"
    assert film.columns[0].formatted_type == "integer"
    assert film.columns[0].nullable is False


@pytest.mark.integration
def test_reads_pagila_primary_and_foreign_keys(
    connector: PostgreSQLConnector,
) -> None:
    snapshot = connector.read_metadata(
        ("public",),
        (
            "public.film",
            "public.language",
            "public.film_actor",
            "public.actor",
        ),
    )

    primary_keys = {
        key.constraint_name: key
        for key in snapshot.primary_keys
    }
    assert primary_keys["film_pkey"].columns == ("film_id",)
    assert primary_keys["film_actor_pkey"].columns == (
        "actor_id",
        "film_id",
    )

    foreign_keys = {
        key.constraint_name: key
        for key in snapshot.foreign_keys
    }
    language_key = foreign_keys["film_language_id_fkey"]
    assert (
        language_key.source_schema,
        language_key.source_table,
        language_key.source_columns,
    ) == ("public", "film", ("language_id",))
    assert (
        language_key.target_schema,
        language_key.target_table,
        language_key.target_columns,
    ) == ("public", "language", ("language_id",))


@pytest.mark.integration
def test_reads_pagila_independent_unique_indexes(
    connector: PostgreSQLConnector,
) -> None:
    snapshot = connector.read_metadata(
        ("public",),
        ("public.store", "public.rental"),
    )
    indexes = {
        index.index_name: index
        for index in snapshot.unique_indexes
    }

    assert indexes["idx_unq_manager_staff_id"].columns == (
        "manager_staff_id",
    )
    assert indexes["idx_unq_manager_staff_id"].predicate is None
    assert indexes[
        "idx_unq_rental_rental_date_inventory_id_customer_id"
    ].columns == (
        "rental_date",
        "inventory_id",
        "customer_id",
    )


@pytest.mark.integration
def test_metadata_scope_does_not_reveal_unauthorized_tables(
    connector: PostgreSQLConnector,
) -> None:
    snapshot = connector.read_metadata(
        ("public",),
        ("public.film",),
    )

    assert len(snapshot.tables) == 1
    assert snapshot.foreign_keys == ()
    assert [table.table_name for table in snapshot.tables] == ["film"]
    assert "staff" not in repr(snapshot)

    unknown = connector.read_metadata(
        ("public",),
        ("public.not_a_table",),
    )
    assert unknown == empty_schema_snapshot()


@pytest.mark.integration
def test_metadata_fingerprint_is_stable(
    connector: PostgreSQLConnector,
) -> None:
    allowed_tables = ("public.film", "public.language")

    first = connector.read_metadata(("public",), allowed_tables)
    second = connector.read_metadata(("public",), allowed_tables)

    assert first == second
    assert first.schema_version == second.schema_version
    assert re.fullmatch(r"[0-9a-f]{64}", first.schema_version)
