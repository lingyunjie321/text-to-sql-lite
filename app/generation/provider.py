import json
import math
import socket
from collections.abc import Sequence
from http.client import HTTPException, IncompleteRead
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request

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
from app.http_transport import HTTPTransport, UrllibHTTPTransport

MAX_RESPONSE_BYTES = 1024 * 1024
PROVIDER_CONTRACT_VERSION = "openai-compatible-json-v1"


class LLMProvider(Protocol):
    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        timeout_seconds: float | None = None,
    ) -> GenerationResult: ...


_PUBLIC_ERRORS = {
    "LLM_TIMEOUT": LLMError(
        error_type=ErrorType.TIMEOUT,
        code="LLM_TIMEOUT",
        retryable=True,
        public_message="The model request timed out.",
    ),
    "LLM_CONNECTION_ERROR": LLMError(
        error_type=ErrorType.CONNECTION_ERROR,
        code="LLM_CONNECTION_ERROR",
        retryable=True,
        public_message="The model service is unavailable.",
    ),
    "LLM_RATE_LIMITED": LLMError(
        error_type=ErrorType.RESOURCE_RISK,
        code="LLM_RATE_LIMITED",
        retryable=True,
        public_message="The model service is temporarily unavailable.",
    ),
    "LLM_CAPACITY_ERROR": LLMError(
        error_type=ErrorType.RESOURCE_RISK,
        code="LLM_CAPACITY_ERROR",
        retryable=True,
        public_message="The model service is temporarily unavailable.",
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
    "LLM_INTERNAL_ERROR": LLMError(
        error_type=ErrorType.UNKNOWN,
        code="LLM_INTERNAL_ERROR",
        retryable=False,
        public_message="The model request failed.",
    ),
}


def _provider_error(code: str) -> LLMProviderError:
    return LLMProviderError(_PUBLIC_ERRORS[code])


def normalize_llm_provider_error(details: LLMError) -> LLMError:
    return _PUBLIC_ERRORS.get(
        details.code,
        _PUBLIC_ERRORS["LLM_INTERNAL_ERROR"],
    )


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

    @property
    def model_id(self) -> str:
        return self._settings.model

    @property
    def endpoint_summary(self) -> str:
        parsed = urlsplit(str(self._settings.base_url))
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = host
        if parsed.port is not None:
            netloc = f"{host}:{parsed.port}"
        return urlunsplit(
            (parsed.scheme, netloc, parsed.path, "", "")
        )

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        if timeout_seconds is None:
            effective_timeout = self._settings.timeout_seconds
        else:
            if (
                type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds)
                or timeout_seconds <= 0
            ):
                raise ValueError("provider timeout is invalid")
            effective_timeout = min(
                self._settings.timeout_seconds,
                timeout_seconds,
            )
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
                timeout=effective_timeout,
            ) as response:
                response_body = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            if error.code == 429:
                code = "LLM_RATE_LIMITED"
            elif error.code in {502, 503, 504}:
                code = "LLM_CAPACITY_ERROR"
            else:
                code = "LLM_HTTP_ERROR"
            raise _provider_error(code) from None
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
            prompt_version=(
                messages[0].prompt_version
                if messages
                else PROMPT_VERSION
            ),
        )
