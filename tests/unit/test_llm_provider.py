import json
import socket
from http.client import BadStatusLine, IncompleteRead
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from app.config import LLMSettings
from app.connectors.errors import ErrorType
from app.generation.models import PROMPT_VERSION
from app.generation import (
    LLMMessage,
    LLMProviderError,
    OpenAICompatibleLLMProvider,
)
from app.generation.provider import MAX_RESPONSE_BYTES


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        read_error: Exception | None = None,
    ) -> None:
        self.body = body
        self.read_error = read_error

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
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

    def open(self, request: Request, *, timeout: float) -> FakeResponse:
        self.calls.append((request, timeout))
        if self.error is not None:
            raise self.error
        return FakeResponse(
            self.body,
            read_error=self.read_error,
        )


def _settings() -> LLMSettings:
    return LLMSettings(
        base_url="https://models.example.test/v1",
        api_key="stage5-test-secret",
        model="model-a",
    )


def _messages() -> tuple[LLMMessage, ...]:
    return (
        LLMMessage(role="system", content="system rules"),
        LLMMessage(role="user", content='{"question":"films"}'),
    )


def _response(
    output: dict[str, object],
    *,
    usage: dict[str, object] | None = None,
    finish_reason: object = "stop",
) -> bytes:
    payload = {
        "model": "provider-reported-model",
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(output),
                }
            }
        ],
    }
    if usage is not None:
        payload["usage"] = usage
    return json.dumps(payload).encode("utf-8")


def test_provider_sends_openai_compatible_structured_request() -> None:
    transport = FakeTransport(
        body=_response(
            {"sql": "SELECT 1", "clarification_reason": None},
            usage={"prompt_tokens": 12, "completion_tokens": 4},
        )
    )
    provider = OpenAICompatibleLLMProvider(
        _settings(),
        transport=transport,
    )

    result = provider.generate(_messages())

    assert result.output.sql == "SELECT 1"
    assert result.input_tokens == 12
    assert result.output_tokens == 4
    assert result.model == "model-a"
    assert result.prompt_version == PROMPT_VERSION
    assert len(transport.calls) == 1
    request, timeout = transport.calls[0]
    assert request.full_url == (
        "https://models.example.test/v1/chat/completions"
    )
    assert request.method == "POST"
    assert timeout == 30
    assert request.get_header("Authorization") == (
        "Bearer stage5-test-secret"
    )
    assert request.get_header("Content-type") == "application/json"
    request_body = json.loads(bytes(request.data or b""))
    assert request_body == {
        "messages": [
            {"content": "system rules", "role": "system"},
            {"content": '{"question":"films"}', "role": "user"},
        ],
        "model": "model-a",
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    assert "stage5-test-secret" not in bytes(request.data or b"").decode()


def test_provider_applies_the_stricter_per_call_timeout() -> None:
    transport = FakeTransport(
        body=_response(
            {"sql": "SELECT 1", "clarification_reason": None},
        )
    )
    provider = OpenAICompatibleLLMProvider(
        _settings(),
        transport=transport,
    )

    provider.generate(_messages(), timeout_seconds=4.25)

    assert transport.calls[0][1] == 4.25


def test_provider_never_expands_its_configured_timeout() -> None:
    transport = FakeTransport(
        body=_response(
            {"sql": "SELECT 1", "clarification_reason": None},
        )
    )
    provider = OpenAICompatibleLLMProvider(
        _settings(),
        transport=transport,
    )

    provider.generate(_messages(), timeout_seconds=60)

    assert transport.calls[0][1] == 30


@pytest.mark.parametrize(
    "timeout_seconds",
    (0, -1, True, float("inf"), float("nan")),
)
def test_provider_rejects_invalid_per_call_timeout(
    timeout_seconds: object,
) -> None:
    provider = OpenAICompatibleLLMProvider(
        _settings(),
        transport=FakeTransport(),
    )

    with pytest.raises(
        ValueError,
        match=r"^provider timeout is invalid$",
    ):
        provider.generate(
            _messages(),
            timeout_seconds=timeout_seconds,  # type: ignore[arg-type]
        )


def test_provider_accepts_clarification_and_missing_usage() -> None:
    provider = OpenAICompatibleLLMProvider(
        _settings(),
        transport=FakeTransport(
            body=_response(
                {
                    "sql": None,
                    "clarification_reason": "Which store?",
                }
            )
        ),
    )

    result = provider.generate(_messages())

    assert result.output.sql is None
    assert result.output.clarification_reason == "Which store?"
    assert result.input_tokens == 0
    assert result.output_tokens == 0


@pytest.mark.parametrize(
    ("error", "error_type", "code"),
    [
        (
            TimeoutError("raw timeout"),
            ErrorType.TIMEOUT,
            "LLM_TIMEOUT",
        ),
        (
            socket.timeout("raw socket timeout"),
            ErrorType.TIMEOUT,
            "LLM_TIMEOUT",
        ),
        (
            URLError("raw connection"),
            ErrorType.CONNECTION_ERROR,
            "LLM_CONNECTION_ERROR",
        ),
        (
            HTTPError(
                "https://models.example.test/v1/chat/completions",
                500,
                "raw provider failure",
                {},
                None,
            ),
            ErrorType.UNKNOWN,
            "LLM_HTTP_ERROR",
        ),
        *(
            (
                HTTPError(
                    "https://models.example.test/v1/chat/completions",
                    status,
                    "raw non-retryable provider failure",
                    {},
                    None,
                ),
                ErrorType.UNKNOWN,
                "LLM_HTTP_ERROR",
            )
            for status in (400, 401, 403, 404)
        ),
        (
            HTTPError(
                "https://models.example.test/v1/chat/completions",
                429,
                "raw provider rate limit",
                {},
                None,
            ),
            ErrorType.RESOURCE_RISK,
            "LLM_RATE_LIMITED",
        ),
        (
            HTTPError(
                "https://models.example.test/v1/chat/completions",
                503,
                "raw provider capacity failure",
                {},
                None,
            ),
            ErrorType.RESOURCE_RISK,
            "LLM_CAPACITY_ERROR",
        ),
        (
            HTTPError(
                "https://models.example.test/v1/chat/completions",
                502,
                "raw bad gateway",
                {},
                None,
            ),
            ErrorType.RESOURCE_RISK,
            "LLM_CAPACITY_ERROR",
        ),
        (
            HTTPError(
                "https://models.example.test/v1/chat/completions",
                504,
                "raw gateway timeout",
                {},
                None,
            ),
            ErrorType.RESOURCE_RISK,
            "LLM_CAPACITY_ERROR",
        ),
        (
            BadStatusLine("private provider status line"),
            ErrorType.CONNECTION_ERROR,
            "LLM_CONNECTION_ERROR",
        ),
    ],
)
def test_provider_normalizes_transport_errors(
    error: Exception,
    error_type: ErrorType,
    code: str,
) -> None:
    provider = OpenAICompatibleLLMProvider(
        _settings(),
        transport=FakeTransport(error=error),
    )

    with pytest.raises(LLMProviderError) as captured:
        provider.generate(_messages())

    assert captured.value.details.error_type is error_type
    assert captured.value.details.code == code
    assert captured.value.__cause__ is None
    assert "private provider" not in str(captured.value)


def test_provider_sanitizes_incomplete_response_read_errors() -> None:
    provider = OpenAICompatibleLLMProvider(
        _settings(),
        transport=FakeTransport(
            read_error=IncompleteRead(
                b"private provider response body",
                100,
            )
        ),
    )

    with pytest.raises(LLMProviderError) as captured:
        provider.generate(_messages())

    assert captured.value.details.code == "LLM_INVALID_RESPONSE"
    assert captured.value.__cause__ is None
    assert "private provider" not in (
        str(captured.value) + repr(captured.value)
    )


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (b"not json", "LLM_INVALID_RESPONSE"),
        (b"{}", "LLM_INVALID_RESPONSE"),
        (
            _response(
                {"sql": "SELECT 1", "clarification_reason": "Both"}
            ),
            "LLM_INVALID_OUTPUT",
        ),
        (
            _response(
                {"sql": "SELECT 1"},
                usage={"prompt_tokens": -1, "completion_tokens": 1},
            ),
            "LLM_INVALID_RESPONSE",
        ),
        (
            _response(
                {"sql": "SELECT 1"},
                finish_reason="length",
            ),
            "LLM_INVALID_RESPONSE",
        ),
        (
            b"x" * (MAX_RESPONSE_BYTES + 1),
            "LLM_INVALID_RESPONSE",
        ),
        (
            b'{"number":' + b"9" * 5000 + b"}",
            "LLM_INVALID_RESPONSE",
        ),
        (
            b"[" * 1500 + b"0" + b"]" * 1500,
            "LLM_INVALID_RESPONSE",
        ),
    ],
)
def test_provider_fails_closed_on_invalid_responses(
    body: bytes,
    code: str,
) -> None:
    provider = OpenAICompatibleLLMProvider(
        _settings(),
        transport=FakeTransport(body=body),
    )

    with pytest.raises(LLMProviderError) as captured:
        provider.generate(_messages())

    assert captured.value.details.code == code
