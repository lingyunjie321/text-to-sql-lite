"""MySQL 8.4 + Sakila 真实 Connector 契约测试。"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.connectors.catalog import discover_metadata
from app.connectors.errors import DatabaseConnectorError, ErrorType
from app.connectors.mysql import MySQLConnector


def _local_environment() -> dict[str, str]:
    path = Path(".env.mysql.local")
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _setting(name: str, local_name: str) -> str | None:
    return os.environ.get(name) or _local_environment().get(local_name)


@pytest.fixture(scope="module")
def mysql_connection_values() -> dict[str, object]:
    password = _setting(
        "TEXT_TO_SQL_MYSQL_PASSWORD",
        "MYSQL_APP_PASSWORD",
    )
    if password is None:
        pytest.skip(
            "MySQL contract requires TEXT_TO_SQL_MYSQL_PASSWORD or "
            ".env.mysql.local"
        )
    return {
        "host": os.environ.get("TEXT_TO_SQL_MYSQL_HOST", "127.0.0.1"),
        "port": int(
            _setting("TEXT_TO_SQL_MYSQL_PORT", "MYSQL_HOST_PORT")
            or "53306"
        ),
        "user": os.environ.get(
            "TEXT_TO_SQL_MYSQL_USERNAME",
            "text_to_sql_reader",
        ),
        "password": password,
        "database": os.environ.get(
            "TEXT_TO_SQL_MYSQL_DATABASE",
            "sakila",
        ),
        "pool_timeout_seconds": 2.0,
        "statement_timeout_seconds": 2,
        "connection_retry_count": 0,
    }


@pytest.fixture
def mysql_connector(
    mysql_connection_values: dict[str, object],
) -> Iterator[MySQLConnector]:
    connector = MySQLConnector(**mysql_connection_values)
    connector.open()
    try:
        yield connector
    finally:
        connector.close()


@pytest.mark.integration
def test_connects_and_reads_json_safe_values(
    mysql_connector: MySQLConnector,
) -> None:
    result = mysql_connector.execute(
        "SELECT NULL AS missing_value, CAST(1.23 AS DECIMAL(10,2)) AS amount"
    )

    assert result.returned_row_count == 1
    assert result.rows == [[None, "1.23"]]


@pytest.mark.integration
def test_discovers_all_non_system_sakila_tables_and_views(
    mysql_connector: MySQLConnector,
) -> None:
    discovered = discover_metadata(mysql_connector, dialect="mysql")
    identities = {
        (relation.qualified_name, relation.relation_kind)
        for relation in discovered.relations
    }

    assert discovered.truncated is False
    assert len(identities) == 23
    assert ("sakila.actor", "table") in identities
    assert ("sakila.actor_info", "view") in identities
    assert discovered.snapshot.schemas == ("sakila",)


@pytest.mark.integration
def test_reads_multi_table_columns_primary_keys_and_foreign_keys(
    mysql_connector: MySQLConnector,
) -> None:
    snapshot = mysql_connector.read_metadata(
        ("sakila",),
        (
            "sakila.actor",
            "sakila.actor_info",
            "sakila.film_actor",
            "sakila.film",
        ),
    )

    relation_kinds = {
        table.table_name: table.relation_kind for table in snapshot.tables
    }
    assert relation_kinds == {
        "actor": "table",
        "actor_info": "view",
        "film": "table",
        "film_actor": "table",
    }
    actor = next(
        table for table in snapshot.tables if table.table_name == "actor"
    )
    assert tuple(column.column_name for column in actor.columns) == (
        "actor_id",
        "first_name",
        "last_name",
        "last_update",
    )
    assert any(
        key.table_name == "actor" and key.columns == ("actor_id",)
        for key in snapshot.primary_keys
    )
    assert any(
        key.source_table == "film_actor"
        and key.target_table == "actor"
        and key.source_columns == ("actor_id",)
        for key in snapshot.foreign_keys
    )


@pytest.mark.integration
def test_database_account_and_transaction_both_reject_writes(
    mysql_connector: MySQLConnector,
) -> None:
    with pytest.raises(DatabaseConnectorError) as captured:
        mysql_connector.execute(
            "UPDATE actor SET first_name = 'blocked' WHERE actor_id = 1"
        )

    assert captured.value.details.error_type is ErrorType.PERMISSION_DENIED


@pytest.mark.integration
def test_statement_timeout_is_enforced(
    mysql_connector: MySQLConnector,
) -> None:
    with pytest.raises(DatabaseConnectorError) as captured:
        mysql_connector.execute(
            "SELECT SUM(f1.length + f2.length + f3.length) FROM film AS f1 "
            "CROSS JOIN film AS f2 CROSS JOIN film AS f3",
            timeout_seconds=0.05,
        )

    assert captured.value.details.error_type is ErrorType.TIMEOUT


@pytest.mark.integration
def test_result_rows_are_capped_and_marked_truncated(
    mysql_connection_values: dict[str, object],
) -> None:
    connector = MySQLConnector(
        **mysql_connection_values,
        max_result_rows=2,
    )
    connector.open()
    try:
        result = connector.execute(
            "SELECT actor_id FROM actor ORDER BY actor_id"
        )
    finally:
        connector.close()

    assert result.returned_row_count == 2
    assert result.truncated is True
