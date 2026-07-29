from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.generation.normalization import normalize_generated_sql


PAYMENT_SNAPSHOT = build_schema_snapshot(
    tables=(
        TableMetadata(
            schema_name="public",
            table_name="payment",
            relation_kind="table",
            comment=None,
            columns=(
                ColumnMetadata(
                    schema_name="public",
                    table_name="payment",
                    column_name="payment_date",
                    ordinal_position=1,
                    data_type="timestamptz",
                    formatted_type="timestamp with time zone",
                    nullable=False,
                    comment=None,
                ),
                ColumnMetadata(
                    schema_name="public",
                    table_name="payment",
                    column_name="amount",
                    ordinal_position=2,
                    data_type="numeric",
                    formatted_type="numeric(5,2)",
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


def test_count_column_alias_uses_counted_entity_name() -> None:
    sql = (
        "SELECT rating, COUNT(film_id) AS rating_count "
        "FROM public.film GROUP BY rating"
    )

    assert normalize_generated_sql(sql) == (
        "SELECT rating, COUNT(film_id) AS film_count "
        "FROM public.film GROUP BY rating"
    )


def test_count_alias_normalization_preserves_unrelated_sql_text() -> None:
    sql = (
        "select /* keep */ count(public.inventory.inventory_id) "
        'as "wrong alias" from public.inventory'
    )

    assert normalize_generated_sql(sql) == (
        "select /* keep */ count(public.inventory.inventory_id) "
        "as inventory_count from public.inventory"
    )


def test_sum_column_alias_uses_summed_value_name() -> None:
    sql = (
        "SELECT customer_id, SUM(p.amount) AS total_payment "
        "FROM payment AS p GROUP BY customer_id"
    )

    assert normalize_generated_sql(sql) == (
        "SELECT customer_id, SUM(p.amount) AS total_amount "
        "FROM payment AS p GROUP BY customer_id"
    )


def test_wrapped_single_sum_uses_summed_value_name() -> None:
    sql = (
        "SELECT COALESCE(SUM(p.amount), 0) AS total_payment "
        "FROM payment AS p"
    )

    assert normalize_generated_sql(sql) == (
        "SELECT COALESCE(SUM(p.amount), 0) AS total_amount "
        "FROM payment AS p"
    )


def test_direct_column_alias_uses_source_column_name() -> None:
    sql = (
        "SELECT c.customer_id AS id, c.first_name AS customer_name "
        "FROM customer AS c"
    )

    assert normalize_generated_sql(sql) == (
        "SELECT c.customer_id AS customer_id, c.first_name AS first_name "
        "FROM customer AS c"
    )


def test_time_truncation_alias_is_derived_from_column_and_unit() -> None:
    sql = (
        "SELECT DATE_TRUNC('month', payment_date) AS month "
        "FROM payment GROUP BY month"
    )

    assert normalize_generated_sql(
        sql,
        snapshot=PAYMENT_SNAPSHOT,
    ) == (
        "SELECT DATE_TRUNC('month', payment_date) AS payment_month "
        "FROM payment GROUP BY payment_month"
    )


def test_alias_matching_a_real_source_column_is_not_rewritten() -> None:
    sql = (
        "SELECT SUM(amount) AS amount FROM payment "
        "ORDER BY amount"
    )

    assert normalize_generated_sql(
        sql,
        snapshot=PAYMENT_SNAPSHOT,
    ) == sql


def test_alias_normalization_rejects_existing_target_collision() -> None:
    sql = (
        "SELECT COUNT(amount) AS payments, "
        "1 AS amount_count FROM payment ORDER BY payments"
    )

    assert normalize_generated_sql(
        sql,
        snapshot=PAYMENT_SNAPSHOT,
    ) == sql


def test_alias_normalization_rejects_duplicate_proposed_targets() -> None:
    sql = (
        "SELECT COUNT(amount) AS payments, "
        "COUNT(amount) AS charges FROM payment ORDER BY payments"
    )

    assert normalize_generated_sql(
        sql,
        snapshot=PAYMENT_SNAPSHOT,
    ) == sql


def test_alias_collision_never_rebinds_group_or_order_reference() -> None:
    sql = (
        "SELECT payment_date, SUM(amount) AS payments, "
        "0 AS total_amount FROM payment "
        "GROUP BY payment_date, total_amount ORDER BY payments"
    )

    assert normalize_generated_sql(
        sql,
        snapshot=PAYMENT_SNAPSHOT,
    ) == sql


def test_count_star_and_unaliased_count_are_not_rewritten() -> None:
    for sql in (
        "SELECT COUNT(*) AS row_count FROM film",
        "SELECT COUNT(film_id) FROM film",
    ):
        assert normalize_generated_sql(sql) == sql


def test_unparseable_sql_is_left_for_the_validator() -> None:
    sql = "SELECT ("

    assert normalize_generated_sql(sql) == sql
