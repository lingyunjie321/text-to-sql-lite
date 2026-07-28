from urllib.error import HTTPError

import pytest

from app.config import LLMSettings
from app.generation import (
    LLMMessage,
    LLMProviderError,
    OpenAICompatibleLLMProvider,
)
from tests.unit.test_llm_provider import FakeTransport


SECRET = "stage5-never-leak-secret"
URL = "https://models.example.test/v1"
PROMPT = "private prompt and SELECT secret_column FROM hidden"
BODY = b'{"error":"private provider body and DELETE FROM film"}'


def test_provider_error_exposes_only_fixed_public_details() -> None:
    settings = LLMSettings(
        base_url=URL,
        api_key=SECRET,
        model="model-a",
    )
    http_error = HTTPError(
        f"{URL}/chat/completions",
        500,
        BODY.decode(),
        {},
        None,
    )
    provider = OpenAICompatibleLLMProvider(
        settings,
        transport=FakeTransport(error=http_error),
    )

    with pytest.raises(LLMProviderError) as captured:
        provider.generate(
            (
                LLMMessage(role="system", content="system"),
                LLMMessage(role="user", content=PROMPT),
            )
        )

    public_error = (
        str(captured.value)
        + repr(captured.value)
        + repr(captured.value.details)
        + repr(provider)
    )
    for sensitive in (SECRET, URL, PROMPT, BODY.decode(), "DELETE FROM film"):
        assert sensitive not in public_error
    assert SECRET not in repr(settings)
