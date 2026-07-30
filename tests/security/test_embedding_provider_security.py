from http.client import IncompleteRead
from urllib.error import HTTPError

import pytest

from tests.unit.test_embedding_provider import FakeTransport


SECRET = "embedding-never-leak-secret"
URL = "https://embeddings.example.test/v1"
DOCUMENT = "private document SELECT secret_column FROM hidden"
BODY = b'{"error":"private provider body and DELETE FROM film"}'


@pytest.mark.parametrize(
    ("transport", "expected_code"),
    (
        (
            FakeTransport(
                error=HTTPError(
                    f"{URL}/embeddings",
                    500,
                    BODY.decode(),
                    {},
                    None,
                )
            ),
            "EMBEDDING_HTTP_ERROR",
        ),
        (
            FakeTransport(
                read_error=IncompleteRead(BODY, len(BODY) + 10)
            ),
            "EMBEDDING_INVALID_RESPONSE",
        ),
        (
            FakeTransport(body=BODY),
            "EMBEDDING_INVALID_RESPONSE",
        ),
    ),
)
def test_embedding_errors_expose_only_fixed_public_details(
    transport: FakeTransport,
    expected_code: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.config import EmbeddingSettings
    from app.schema_linking.embedding import (
        EmbeddingProviderError,
        OpenAICompatibleEmbeddingProvider,
    )

    settings = EmbeddingSettings(
        base_url=URL,
        api_key=SECRET,
        model="private-model",
        dimension=3,
    )
    provider = OpenAICompatibleEmbeddingProvider(
        settings,
        transport=transport,
    )

    with pytest.raises(EmbeddingProviderError) as captured:
        provider.embed((DOCUMENT,))

    rendered = (
        str(captured.value)
        + repr(captured.value)
        + repr(captured.value.details)
        + repr(provider)
        + repr(settings)
        + caplog.text
    )
    assert captured.value.details.code == expected_code
    assert captured.value.__cause__ is None
    for sensitive in (
        SECRET,
        URL,
        DOCUMENT,
        BODY.decode(),
        "private-model",
        "DELETE FROM film",
    ):
        assert sensitive not in rendered


def test_embedding_provider_redacts_invalid_utf8_input() -> None:
    from app.config import EmbeddingSettings
    from app.schema_linking.embedding import (
        EmbeddingProviderError,
        OpenAICompatibleEmbeddingProvider,
    )

    document = "private-document-\ud800-suffix"
    provider = OpenAICompatibleEmbeddingProvider(
        EmbeddingSettings(
            base_url=URL,
            api_key=SECRET,
            model="private-model",
            dimension=3,
        ),
        transport=FakeTransport(body=b""),
    )

    with pytest.raises(EmbeddingProviderError) as captured:
        provider.embed((document,))

    assert captured.value.details.code == "EMBEDDING_INVALID_INPUT"
    assert captured.value.__cause__ is None
    assert document not in (
        str(captured.value) + repr(captured.value)
    )
