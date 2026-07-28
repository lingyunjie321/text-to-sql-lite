from app.generation.models import (
    GenerationContext,
    GenerationResult,
)
from app.generation.prompt import build_generation_messages
from app.generation.provider import LLMProvider


def generate_sql(
    context: GenerationContext,
    *,
    provider: LLMProvider,
) -> GenerationResult:
    messages = build_generation_messages(context)
    return provider.generate(messages)
