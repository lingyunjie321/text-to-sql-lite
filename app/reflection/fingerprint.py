import hashlib

from sqlglot import ErrorLevel, parse
from sqlglot.errors import ParseError, SqlglotError
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers


def sql_fingerprint(sql: str) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql cannot be empty")

    try:
        expressions = [
            expression
            for expression in parse(
                sql,
                read="postgres",
                error_level=ErrorLevel.RAISE,
            )
            if expression
        ]
        if not expressions:
            raise ParseError("empty SQL")
        fingerprint_source = "; ".join(
            normalize_identifiers(
                expression.copy(),
                dialect="postgres",
            ).sql(
                dialect="postgres",
                unsupported_level=ErrorLevel.RAISE,
                comments=False,
            )
            for expression in expressions
        )
    except SqlglotError:
        fingerprint_source = sql

    return hashlib.sha256(
        fingerprint_source.encode("utf-8")
    ).hexdigest()
