import hashlib

from sqlglot import ErrorLevel, parse
from sqlglot.errors import ParseError, SqlglotError
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers


def sql_fingerprint(sql: str) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql cannot be empty")

    fingerprint_source = sql
    for dialect in ("postgres", "mysql"):
        try:
            expressions = [
                expression
                for expression in parse(
                    sql,
                    read=dialect,
                    error_level=ErrorLevel.RAISE,
                )
                if expression
            ]
            if not expressions:
                raise ParseError("empty SQL")
            fingerprint_source = "; ".join(
                normalize_identifiers(
                    expression.copy(),
                    dialect=dialect,
                ).sql(
                    dialect=dialect,
                    unsupported_level=ErrorLevel.RAISE,
                    comments=False,
                )
                for expression in expressions
            )
            break
        except SqlglotError:
            continue

    return hashlib.sha256(
        fingerprint_source.encode("utf-8")
    ).hexdigest()
