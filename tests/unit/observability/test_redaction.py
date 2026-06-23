from text_to_sql_demo.observability.redaction import (
    REDACTED,
    exception_location,
    redact_mapping,
    sanitize_database_url,
    summarize_sql,
)


def test_redact_mapping_masks_sensitive_keys_recursively() -> None:
    payload = {
        "api_key": "sk-secret",
        "nested": {
            "Authorization": "Bearer token",
            "items": [{"password": "db-secret"}, {"safe": "value"}],
        },
    }

    redacted = redact_mapping(payload)

    assert redacted == {
        "api_key": REDACTED,
        "nested": {
            "Authorization": REDACTED,
            "items": [{"password": REDACTED}, {"safe": "value"}],
        },
    }


def test_sanitize_database_url_hides_password_but_keeps_route_context() -> None:
    url = "postgresql+psycopg://readonly:secret@db.example.com:5432/analytics?sslmode=require"

    sanitized = sanitize_database_url(url)

    assert "secret" not in sanitized
    assert "readonly" in sanitized
    assert "db.example.com" in sanitized
    assert "analytics" in sanitized
    assert "***" in sanitized


def test_summarize_sql_hides_preview_by_default() -> None:
    sql = "SELECT id, amount FROM orders WHERE amount > 10"

    summary = summarize_sql(sql)

    assert summary["sql_length"] == len(sql)
    assert summary["sql_hash"]
    assert "sql_preview" not in summary


def test_summarize_sql_includes_limited_preview_when_debug_enabled() -> None:
    sql = "SELECT id, amount FROM orders WHERE amount > 10"

    summary = summarize_sql(sql, include_preview=True, max_preview_chars=12)

    assert summary["sql_preview"] == "SELECT id, a"
    assert summary["sql_length"] == len(sql)


def test_exception_location_points_to_original_raise_site() -> None:
    try:
        _raise_sample_error()
    except RuntimeError as exc:
        location = exception_location(exc)

    assert location["error_file"].endswith("test_redaction.py")
    assert location["error_function"] == "_raise_sample_error"
    assert isinstance(location["error_line"], int)
    assert location["error_line"] > 0


def _raise_sample_error() -> None:
    raise RuntimeError("boom")

