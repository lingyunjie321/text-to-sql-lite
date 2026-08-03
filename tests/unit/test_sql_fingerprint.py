import hashlib

import pytest

from app.reflection import sql_fingerprint


def test_parseable_formatting_has_one_stable_fingerprint() -> None:
    variants = (
        "select film_id from film",
        "SELECT film_id FROM film;",
        "  SELECT  film_id\nFROM film  ",
        "SELECT FILM_ID FROM FILM",
        "SELECT film_id FROM film -- ignored comment\n",
        "SELECT /* ignored */ film_id FROM film",
    )

    assert len({sql_fingerprint(sql) for sql in variants}) == 1


def test_mysql_quoted_identifier_formatting_has_one_stable_fingerprint():
    variants = (
        "select `film_id` from `film`",
        "SELECT `film_id` FROM `film`;",
        "  SELECT  `film_id`\nFROM `film`  ",
    )

    assert len({sql_fingerprint(sql) for sql in variants}) == 1


def test_quoted_identifier_case_remains_distinct() -> None:
    assert (
        sql_fingerprint('SELECT "FILM_ID" FROM "FILM"')
        != sql_fingerprint("SELECT film_id FROM film")
    )


def test_different_parseable_sql_has_different_fingerprints() -> None:
    assert (
        sql_fingerprint("SELECT film_id FROM film")
        != sql_fingerprint("SELECT title FROM film")
    )


def test_parseable_multiple_statements_are_canonicalized() -> None:
    assert sql_fingerprint("select 1; select 2") == sql_fingerprint(
        "SELECT 1 ;\nSELECT 2;"
    )


@pytest.mark.parametrize(
    "raw_sql",
    ["SELECT (", "'", "/*", "SELECT /*", 'SELECT "x'],
)
def test_parse_failure_hashes_exact_raw_sql(raw_sql: str) -> None:

    assert sql_fingerprint(raw_sql) == hashlib.sha256(
        raw_sql.encode("utf-8")
    ).hexdigest()
    assert sql_fingerprint(raw_sql) != sql_fingerprint(f"{raw_sql} ")


@pytest.mark.parametrize("sql", ["", " ", "\n\t"])
def test_empty_sql_is_rejected(sql: str) -> None:
    with pytest.raises(ValueError, match="sql cannot be empty"):
        sql_fingerprint(sql)
