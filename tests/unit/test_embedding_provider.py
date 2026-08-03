import json
import socket
from http.client import BadStatusLine, IncompleteRead
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest
from pydantic import ValidationError

from app.connectors.errors import ErrorType


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        read_error: Exception | None = None,
    ) -> None:
        self.body = body
        self.read_error = read_error
        self.read_amounts: list[int] = []

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        self.read_amounts.append(amount)
        if self.read_error is not None:
            raise self.read_error
        return self.body if amount < 0 else self.body[:amount]


class FakeTransport:
    def __init__(
        self,
        *,
        body: bytes = b"",
        error: Exception | None = None,
        read_error: Exception | None = None,
    ) -> None:
        self.body = body
        self.error = error
        self.read_error = read_error
        self.calls: list[tuple[Request, float]] = []
        self.responses: list[FakeResponse] = []

    def open(self, request: Request, *, timeout: float) -> FakeResponse:
        self.calls.append((request, timeout))
        if self.error is not None:
            raise self.error
        response = FakeResponse(
            self.body,
            read_error=self.read_error,
        )
        self.responses.append(response)
        return response


def _settings(**overrides: object):
    from app.config import EmbeddingSettings

    values: dict[str, object] = {
        "base_url": "https://embeddings.example.test/v1",
        "api_key": "embedding-test-secret",
        "model": "embedding-v1",
        "dimension": 3,
    }
    values.update(overrides)
    return EmbeddingSettings(**values)


_MODEL_OMITTED = object()


def _response(
    data: object,
    *,
    model: object = "embedding-v1",
) -> bytes:
    payload: dict[str, object] = {"data": data}
    if model is not _MODEL_OMITTED:
        payload["model"] = model
    return json.dumps(payload).encode("utf-8")


def _provider(
    *,
    body: bytes,
    settings=None,
    transport: FakeTransport | None = None,
):
    from app.schema_linking.embedding import (
        OpenAICompatibleEmbeddingProvider,
    )

    selected_transport = transport or FakeTransport(body=body)
    return (
        OpenAICompatibleEmbeddingProvider(
            settings or _settings(),
            transport=selected_transport,
        ),
        selected_transport,
    )


def test_embedding_settings_load_explicit_env_and_keep_secret_safe(
    tmp_path: Path,
) -> None:
    from app.config import load_embedding_settings

    env_file = tmp_path / ".env"
    env_file.write_text(
        "EMBEDDING_BASE_URL=https://embeddings.example.test/v1\n"
        "EMBEDDING_API_KEY=embedding-test-secret\n"
        "EMBEDDING_MODEL=text-embedding-v4\n"
        "EMBEDDING_DIMENSION=1024\n",
        encoding="utf-8",
    )

    settings = load_embedding_settings(env_file)

    assert str(settings.base_url) == (
        "https://embeddings.example.test/v1"
    )
    assert settings.model == "text-embedding-v4"
    assert settings.dimension == 1024
    assert settings.timeout_seconds == 10
    assert settings.max_batch_documents == 10
    assert settings.max_response_bytes == 4_194_304
    assert settings.api_key_value == "embedding-test-secret"
    assert "embedding-test-secret" not in repr(settings)


@pytest.mark.parametrize(
    "base_url",
    (
        "ftp://embeddings.example.test/v1",
        "http://embeddings.example.test/v1",
        "https://user:password@embeddings.example.test/v1",
        "https://embeddings.example.test/v1?debug=true",
        "https://embeddings.example.test/v1#fragment",
    ),
)
def test_embedding_settings_reject_unsafe_base_urls(
    base_url: str,
) -> None:
    with pytest.raises(ValidationError):
        _settings(base_url=base_url)


@pytest.mark.parametrize(
    "base_url",
    (
        "http://localhost:8000/v1",
        "http://127.0.0.1:8000/v1",
        "http://[::1]:8000/v1",
    ),
)
def test_embedding_settings_allow_loopback_http(
    base_url: str,
) -> None:
    assert _settings(base_url=base_url).base_url.scheme == "http"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("api_key", " "),
        ("api_key", "secret\nInjected: value"),
        ("api_key", "secret-🔒"),
        ("model", " "),
        ("dimension", 0),
        ("dimension", -1),
        ("dimension", True),
        ("dimension", 3.5),
        ("timeout_seconds", 0),
        ("timeout_seconds", 11),
        ("timeout_seconds", True),
        ("max_batch_documents", 65),
        ("max_response_bytes", 4_194_305),
    ),
)
def test_embedding_settings_reject_invalid_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        _settings(**{field: value})


def test_provider_preserves_input_order_and_sends_compatible_request() -> None:
    provider, transport = _provider(
        body=_response(
            [
                {"index": 1, "embedding": [0, 1.0, 0]},
                {"index": 0, "embedding": [1, 0.0, 0]},
            ]
        )
    )

    result = provider.embed(("film", "actor"))

    assert result == (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
    )
    assert provider.model_id == "embedding-v1"
    assert provider.dimension == 3
    assert len(transport.calls) == 1
    request, timeout = transport.calls[0]
    assert request.full_url == (
        "https://embeddings.example.test/v1/embeddings"
    )
    assert request.method == "POST"
    assert timeout == 10
    assert request.get_header("Authorization") == (
        "Bearer embedding-test-secret"
    )
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(bytes(request.data or b"")) == {
        "model": "embedding-v1",
        "input": ["film", "actor"],
    }
    assert "embedding-test-secret" not in bytes(
        request.data or b""
    ).decode("utf-8")
    assert transport.responses[0].read_amounts == [4_194_305]


def test_provider_omits_authorization_when_api_key_is_not_configured() -> None:
    provider, transport = _provider(
        body=_response(
            [{"index": 0, "embedding": [1, 0.0, 0]}]
        ),
        settings=_settings(
            base_url="http://localhost:11434/v1",
            api_key=None,
        ),
    )

    provider.embed(("film",))

    request, _ = transport.calls[0]
    assert request.get_header("Authorization") is None
    assert request.get_header("Content-type") == "application/json"


def test_provider_applies_stricter_per_call_timeout() -> None:
    provider, transport = _provider(
        body=_response(
            [{"index": 0, "embedding": [1, 0, 0]}]
        )
    )

    provider.embed(("film",), timeout_seconds=2.5)

    assert transport.calls[0][1] == 2.5


def test_provider_never_expands_configured_timeout() -> None:
    provider, transport = _provider(
        body=_response(
            [{"index": 0, "embedding": [1, 0, 0]}]
        )
    )

    provider.embed(("film",), timeout_seconds=60)

    assert transport.calls[0][1] == 10


@pytest.mark.parametrize(
    "timeout_seconds",
    (0, -1, True, float("inf"), float("nan")),
)
def test_provider_rejects_invalid_per_call_timeout(
    timeout_seconds: object,
) -> None:
    provider, _ = _provider(body=b"")

    with pytest.raises(
        ValueError,
        match=r"^embedding provider timeout is invalid$",
    ):
        provider.embed(
            ("film",),
            timeout_seconds=timeout_seconds,  # type: ignore[arg-type]
        )


def test_provider_configuration_hash_excludes_secret_and_binds_endpoint() -> None:
    from app.schema_linking.embedding import (
        OpenAICompatibleEmbeddingProvider,
    )

    first = OpenAICompatibleEmbeddingProvider(
        _settings(api_key="first-test-secret")
    )
    secret_change = OpenAICompatibleEmbeddingProvider(
        _settings(api_key="second-test-secret")
    )
    endpoint_change = OpenAICompatibleEmbeddingProvider(
        _settings(
            api_key="first-test-secret",
            base_url="https://other-embeddings.example.test/v1",
        )
    )

    assert first.provider_config_sha256 == (
        secret_change.provider_config_sha256
    )
    assert first.provider_config_sha256 != (
        endpoint_change.provider_config_sha256
    )
    assert "first-test-secret" not in first.provider_config_sha256


def test_provider_accepts_an_omitted_response_model() -> None:
    provider, _ = _provider(
        body=_response(
            [{"index": 0, "embedding": [1, 0, 0]}],
            model=_MODEL_OMITTED,
        )
    )

    assert provider.embed(("film",)) == ((1.0, 0.0, 0.0),)


@pytest.mark.parametrize(
    "texts",
    (
        (),
        (" ",),
        "film",
        1,
        object(),
        {"film": "actor"},
        (text for text in ("film",)),
        ("film", 1),
        tuple(f"document-{index}" for index in range(65)),
    ),
)
def test_provider_rejects_invalid_input_before_transport(
    texts: object,
) -> None:
    from app.schema_linking.embedding import EmbeddingProviderError

    provider, transport = _provider(body=b"")

    with pytest.raises(EmbeddingProviderError) as captured:
        provider.embed(texts)  # type: ignore[arg-type]

    assert captured.value.details.code == "EMBEDDING_INVALID_INPUT"
    assert captured.value.__cause__ is None
    assert transport.calls == []


def test_provider_accepts_the_maximum_batch_size() -> None:
    from app.schema_linking.index import INDEX_EMBEDDING_BATCH_SIZE
    batch = INDEX_EMBEDDING_BATCH_SIZE
    texts = tuple(f"document-{index}" for index in range(batch))
    provider, transport = _provider(
        body=_response(
            [
                {"index": index, "embedding": [1, index, 0]}
                for index in range(batch)
            ]
        )
    )

    result = provider.embed(texts)

    assert len(result) == batch
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "dimension",
    (1023, 1025),
)
def test_provider_enforces_the_configured_1024_dimension(
    dimension: int,
) -> None:
    from app.schema_linking.embedding import EmbeddingProviderError

    provider, _ = _provider(
        settings=_settings(dimension=1024),
        body=_response(
            [
                {
                    "index": 0,
                    "embedding": [1.0] + [0.0] * (dimension - 1),
                }
            ]
        ),
    )

    with pytest.raises(EmbeddingProviderError) as captured:
        provider.embed(("film",))

    assert captured.value.details.code == "EMBEDDING_INVALID_RESPONSE"


def test_provider_accepts_the_configured_1024_dimension() -> None:
    provider, _ = _provider(
        settings=_settings(dimension=1024),
        body=_response(
            [
                {
                    "index": 0,
                    "embedding": [1.0] + [0.0] * 1023,
                }
            ]
        ),
    )

    result = provider.embed(("film",))

    assert len(result[0]) == 1024
    assert result[0][0] == 1.0


@pytest.mark.parametrize(
    "body",
    (
        b"\xff",
        b"not-json",
        b"[]",
        b"{}",
        _response("not-a-list"),
        _response([]),
        _response(
            [
                {"index": 0, "embedding": [1, 0, 0]},
                {"index": 1, "embedding": [0, 1, 0]},
            ]
        ),
        _response([None]),
        _response([{"embedding": [1, 0, 0]}]),
        _response([{"index": True, "embedding": [1, 0, 0]}]),
        _response([{"index": 1, "embedding": [1, 0, 0]}]),
        _response(
            [
                {"index": 0, "embedding": [1, 0, 0]},
                {"index": 0, "embedding": [0, 1, 0]},
            ]
        ),
        _response([{"index": 0}]),
        _response([{"index": 0, "embedding": "not-a-list"}]),
        _response([{"index": 0, "embedding": [1, 0]}]),
        _response([{"index": 0, "embedding": [1, 0, 0, 0]}]),
        _response([{"index": 0, "embedding": [True, 0, 0]}]),
        _response([{"index": 0, "embedding": ["1", 0, 0]}]),
        _response([{"index": 0, "embedding": [float("nan"), 0, 0]}]),
        _response([{"index": 0, "embedding": [float("inf"), 0, 0]}]),
        _response([{"index": 0, "embedding": [0, -0.0, 0]}]),
        _response(
            [{"index": 0, "embedding": [1, 0, 0]}],
            model="other-model",
        ),
        _response(
            [{"index": 0, "embedding": [1, 0, 0]}],
            model=None,
        ),
    ),
)
def test_provider_fails_closed_on_invalid_responses(
    body: bytes,
) -> None:
    from app.schema_linking.embedding import EmbeddingProviderError

    provider, _ = _provider(body=body)

    with pytest.raises(EmbeddingProviderError) as captured:
        provider.embed(("film",))

    assert captured.value.details.code == "EMBEDDING_INVALID_RESPONSE"
    assert captured.value.__cause__ is None


@pytest.mark.parametrize(
    ("error", "error_type", "code"),
    (
        (
            TimeoutError("private timeout"),
            ErrorType.TIMEOUT,
            "EMBEDDING_TIMEOUT",
        ),
        (
            socket.timeout("private socket timeout"),
            ErrorType.TIMEOUT,
            "EMBEDDING_TIMEOUT",
        ),
        (
            URLError(TimeoutError("private wrapped timeout")),
            ErrorType.TIMEOUT,
            "EMBEDDING_TIMEOUT",
        ),
        (
            URLError("private connection"),
            ErrorType.CONNECTION_ERROR,
            "EMBEDDING_CONNECTION_ERROR",
        ),
        (
            BadStatusLine("private status line"),
            ErrorType.CONNECTION_ERROR,
            "EMBEDDING_CONNECTION_ERROR",
        ),
        (
            OSError("private socket failure"),
            ErrorType.CONNECTION_ERROR,
            "EMBEDDING_CONNECTION_ERROR",
        ),
        (
            HTTPError(
                "https://embeddings.example.test/v1/embeddings",
                429,
                "private provider failure",
                {},
                None,
            ),
            ErrorType.UNKNOWN,
            "EMBEDDING_RATE_LIMITED",
        ),
    ),
)
def test_provider_normalizes_transport_errors(
    error: Exception,
    error_type: ErrorType,
    code: str,
) -> None:
    from app.schema_linking.embedding import (
        EmbeddingProviderError,
        OpenAICompatibleEmbeddingProvider,
    )

    provider = OpenAICompatibleEmbeddingProvider(
        _settings(),
        transport=FakeTransport(error=error),
    )

    with pytest.raises(EmbeddingProviderError) as captured:
        provider.embed(("private document",))

    assert captured.value.details.error_type is error_type
    assert captured.value.details.code == code
    assert captured.value.__cause__ is None
    assert "private" not in str(captured.value)


def test_provider_sanitizes_incomplete_reads() -> None:
    from app.schema_linking.embedding import (
        EmbeddingProviderError,
        OpenAICompatibleEmbeddingProvider,
    )

    provider = OpenAICompatibleEmbeddingProvider(
        _settings(),
        transport=FakeTransport(
            read_error=IncompleteRead(
                b"private response body",
                100,
            )
        ),
    )

    with pytest.raises(EmbeddingProviderError) as captured:
        provider.embed(("private document",))

    assert captured.value.details.code == "EMBEDDING_INVALID_RESPONSE"
    assert captured.value.__cause__ is None
    assert "private" not in (
        str(captured.value) + repr(captured.value)
    )


def test_provider_rejects_an_oversized_response() -> None:
    from app.schema_linking.embedding import EmbeddingProviderError

    provider, _ = _provider(body=b"x" * 4_194_305)

    with pytest.raises(EmbeddingProviderError) as captured:
        provider.embed(("film",))

    assert captured.value.details.code == "EMBEDDING_INVALID_RESPONSE"


def test_provider_accepts_a_valid_response_at_the_size_limit() -> None:
    base = _response([{"index": 0, "embedding": [1, 0, 0]}])
    body = base + b" " * (4_194_304 - len(base))
    provider, _ = _provider(body=body)

    assert provider.embed(("film",)) == ((1.0, 0.0, 0.0),)
