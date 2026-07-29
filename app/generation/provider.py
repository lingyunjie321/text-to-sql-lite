import json
import socket
from collections.abc import Sequence
from http.client import HTTPException, IncompleteRead
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)

from pydantic import ValidationError

from app.config import LLMSettings
from app.connectors.errors import ErrorType
from app.generation.models import (
    PROMPT_VERSION,
    GenerationResult,
    GeneratedSQL,
    LLMError,
    LLMMessage,
    LLMProviderError,
)

MAX_RESPONSE_BYTES = 1024 * 1024
PROVIDER_CONTRACT_VERSION = "openai-compatible-json-v1"


class _HTTPResponse(Protocol):
    def __enter__(self) -> "_HTTPResponse": ...

    def __exit__(self, *args: object) -> object: ...

    def read(self, amount: int = -1) -> bytes: ...


class HTTPTransport(Protocol):
    def open(
        self,
        request: Request,
        *,
        timeout: float,
    ) -> _HTTPResponse: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


class UrllibHTTPTransport:
    def __init__(self) -> None:
        self._opener = build_opener(_NoRedirectHandler())

    def open(
        self,
        request: Request,
        *,
        timeout: float,
    ) -> _HTTPResponse:
        return self._opener.open(  # type: ignore[return-value]
            request,
            timeout=timeout,
        )


class LLMProvider(Protocol):
    def generate(
        self,
        messages: Sequence[LLMMessage],
    ) -> GenerationResult: ...


_PUBLIC_ERRORS = {
    "LLM_TIMEOUT": LLMError(
        error_type=ErrorType.TIMEOUT,
        code="LLM_TIMEOUT",
        retryable=False,
        public_message="The model request timed out.",
    ),
    "LLM_CONNECTION_ERROR": LLMError(
        error_type=ErrorType.CONNECTION_ERROR,
        code="LLM_CONNECTION_ERROR",
        retryable=False,
        public_message="The model service is unavailable.",
    ),
    "LLM_HTTP_ERROR": LLMError(
        error_type=ErrorType.UNKNOWN,
        code="LLM_HTTP_ERROR",
        retryable=False,
        public_message="The model request failed.",
    ),
    "LLM_INVALID_RESPONSE": LLMError(
        error_type=ErrorType.UNKNOWN,
        code="LLM_INVALID_RESPONSE",
        retryable=False,
        public_message="The model response is invalid.",
    ),
    "LLM_INVALID_OUTPUT": LLMError(
        error_type=ErrorType.UNKNOWN,
        code="LLM_INVALID_OUTPUT",
        retryable=False,
        public_message="The model output is invalid.",
    ),
}


def _provider_error(code: str) -> LLMProviderError:
    return LLMProviderError(_PUBLIC_ERRORS[code])


def _is_timeout(error: BaseException) -> bool:
    if isinstance(error, (TimeoutError, socket.timeout)):
        return True
    return (
        isinstance(error, URLError)
        and isinstance(error.reason, (TimeoutError, socket.timeout))
    )


def _token_count(usage: dict[str, object], name: str) -> int:
    value = usage.get(name, 0)
    if type(value) is not int or value < 0:
        raise _provider_error("LLM_INVALID_RESPONSE")
    return value


class OpenAICompatibleLLMProvider:
    def __init__(
        self,
        settings: LLMSettings,
        *,
        transport: HTTPTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport or UrllibHTTPTransport()

    def generate(
        self,
        messages: Sequence[LLMMessage],
    ) -> GenerationResult:
        request_body = json.dumps(
            {
                "model": self._settings.model,
                "temperature": self._settings.temperature,
                "messages": [
                    {
                        "role": message.role,
                        "content": message.content,
                    }
                    for message in messages
                ],
                "response_format": {"type": "json_object"},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        endpoint = (
            f"{str(self._settings.base_url).rstrip('/')}"
            "/chat/completions"
        )
        request = Request(
            endpoint,
            data=request_body,
            headers={
                "Authorization": (
                    f"Bearer {self._settings.api_key_value}"
                ),
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with self._transport.open(
                request,
                timeout=self._settings.timeout_seconds,
            ) as response:
                response_body = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError:
            raise _provider_error("LLM_HTTP_ERROR") from None
        except (TimeoutError, socket.timeout):
            raise _provider_error("LLM_TIMEOUT") from None
        except IncompleteRead:
            raise _provider_error("LLM_INVALID_RESPONSE") from None
        except HTTPException:
            raise _provider_error("LLM_CONNECTION_ERROR") from None
        except URLError as error:
            code = (
                "LLM_TIMEOUT"
                if _is_timeout(error)
                else "LLM_CONNECTION_ERROR"
            )
            raise _provider_error(code) from None
        except OSError:
            raise _provider_error("LLM_CONNECTION_ERROR") from None

        if len(response_body) > MAX_RESPONSE_BYTES:
            raise _provider_error("LLM_INVALID_RESPONSE") from None
        try:
            envelope = json.loads(response_body.decode("utf-8"))
            if not isinstance(envelope, dict):
                raise TypeError
            choices = envelope["choices"]
            if not isinstance(choices, list) or not choices:
                raise TypeError
            first_choice = choices[0]
            if not isinstance(first_choice, dict):
                raise TypeError
            if first_choice["finish_reason"] != "stop":
                raise TypeError
            message = first_choice["message"]
            if not isinstance(message, dict):
                raise TypeError
            content = message["content"]
            if not isinstance(content, str):
                raise TypeError
            output_payload = json.loads(content)
            usage_value = envelope.get("usage", {})
            if not isinstance(usage_value, dict):
                raise TypeError
            input_tokens = _token_count(
                usage_value,
                "prompt_tokens",
            )
            output_tokens = _token_count(
                usage_value,
                "completion_tokens",
            )
        except LLMProviderError:
            raise
        except (
            UnicodeDecodeError,
            ValueError,
            RecursionError,
            KeyError,
            TypeError,
        ):
            raise _provider_error("LLM_INVALID_RESPONSE") from None

        try:
            output = GeneratedSQL.model_validate(output_payload)
        except ValidationError:
            raise _provider_error("LLM_INVALID_OUTPUT") from None
        return GenerationResult(
            output=output,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self._settings.model,
            prompt_version=PROMPT_VERSION,
        )
