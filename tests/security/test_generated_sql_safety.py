import pytest

from app.generation import (
    GenerationResult,
    GeneratedSQL,
    LLMMessage,
    generate_sql,
)
from app.validation import validate_sql
from tests.unit.test_generation_service import CONTEXT


class MaliciousProvider:
    def __init__(self, sql: str) -> None:
        self.sql = sql
        self.calls = 0

    def generate(
        self,
        messages: tuple[LLMMessage, ...],
    ) -> GenerationResult:
        self.calls += 1
        return GenerationResult(
            output=GeneratedSQL(sql=self.sql),
            input_tokens=1,
            output_tokens=1,
            model="malicious-stub",
            prompt_version="mvp-v1",
        )


@pytest.mark.parametrize(
    "model_sql",
    [
        "DELETE FROM film",
        "SELECT film_id FROM film; DROP TABLE film",
        "SELECT pg_sleep(1)",
    ],
)
def test_generated_sql_is_never_trusted_or_executed(
    model_sql: str,
) -> None:
    provider = MaliciousProvider(model_sql)

    generated = generate_sql(CONTEXT, provider=provider)
    validation = validate_sql(
        generated.output.sql or "",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=CONTEXT.snapshot,
    )

    assert provider.calls == 1
    assert generated.output.sql == model_sql
    assert validation.is_valid is False
    assert validation.normalized_sql is None
