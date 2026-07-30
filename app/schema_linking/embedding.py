import hashlib
import json
import math
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from http.client import HTTPException, IncompleteRead
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request

from app.config import EmbeddingSettings
from app.connectors.errors import ErrorType
from app.http_transport import HTTPTransport, UrllibHTTPTransport

EMBEDDING_PROVIDER_CONTRACT_VERSION = (
    "openai-compatible-embedding-v1"
)


def embedding_endpoint_identity_sha256(
    settings: EmbeddingSettings,
) -> str:
    if not isinstance(settings, EmbeddingSettings):
        raise ValueError(
            "embedding provider settings are invalid"
        )
    return hashlib.sha256(
        str(settings.base_url).encode("utf-8")
    ).hexdigest()


def embedding_provider_config_sha256(
    settings: EmbeddingSettings,
) -> str:
    if not isinstance(settings, EmbeddingSettings):
        raise ValueError(
            "embedding provider settings are invalid"
        )
    payload = json.dumps(
        {
            "base_url": str(settings.base_url),
            "contract_version": (
                EMBEDDING_PROVIDER_CONTRACT_VERSION
            ),
            "dimension": settings.dimension,
            "max_batch_documents": (
                settings.max_batch_documents
            ),
            "max_response_bytes": (
                settings.max_response_bytes
            ),
            "model": settings.model,
            "timeout_seconds": settings.timeout_seconds,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class EmbeddingProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    @property
    def provider_config_sha256(self) -> str: ...

    def embed(
        self,
        texts: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[tuple[float, ...], ...]: ...


@dataclass(frozen=True, slots=True)
class EmbeddingError:
    error_type: ErrorType
    code: str
    retryable: bool
    public_message: str


class EmbeddingProviderError(RuntimeError):
    def __init__(self, details: EmbeddingError) -> None:
        super().__init__(details.public_message)
        self.details = details


_PUBLIC_ERRORS = {
    "EMBEDDING_INVALID_INPUT": EmbeddingError(
        error_type=ErrorType.UNKNOWN,
        code="EMBEDDING_INVALID_INPUT",
        retryable=False,
        public_message="The embedding input is invalid.",
    ),
    "EMBEDDING_TIMEOUT": EmbeddingError(
        error_type=ErrorType.TIMEOUT,
        code="EMBEDDING_TIMEOUT",
        retryable=False,
        public_message="The embedding request timed out.",
    ),
    "EMBEDDING_CONNECTION_ERROR": EmbeddingError(
        error_type=ErrorType.CONNECTION_ERROR,
        code="EMBEDDING_CONNECTION_ERROR",
        retryable=False,
        public_message="The embedding service is unavailable.",
    ),
    "EMBEDDING_HTTP_ERROR": EmbeddingError(
        error_type=ErrorType.UNKNOWN,
        code="EMBEDDING_HTTP_ERROR",
        retryable=False,
        public_message="The embedding request failed.",
    ),
    "EMBEDDING_RATE_LIMITED": EmbeddingError(
        error_type=ErrorType.UNKNOWN,
        code="EMBEDDING_RATE_LIMITED",
        retryable=False,
        public_message="The embedding service is temporarily busy.",
    ),
    "EMBEDDING_INVALID_RESPONSE": EmbeddingError(
        error_type=ErrorType.UNKNOWN,
        code="EMBEDDING_INVALID_RESPONSE",
        retryable=False,
        public_message="The embedding response is invalid.",
    ),
}


def _provider_error(code: str) -> EmbeddingProviderError:
    return EmbeddingProviderError(_PUBLIC_ERRORS[code])


def _embedding_timeout_error() -> EmbeddingProviderError:
    return _provider_error("EMBEDDING_TIMEOUT")


def _is_timeout(error: BaseException) -> bool:
    if isinstance(error, (TimeoutError, socket.timeout)):
        return True
    return (
        isinstance(error, URLError)
        and isinstance(error.reason, (TimeoutError, socket.timeout))
    )


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        settings: EmbeddingSettings,
        *,
        transport: HTTPTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport or UrllibHTTPTransport()

    @property
    def model_id(self) -> str:
        return self._settings.model

    @property
    def dimension(self) -> int:
        return self._settings.dimension

    @property
    def provider_config_sha256(self) -> str:
        return embedding_provider_config_sha256(
            self._settings
        )

    def embed(
        self,
        texts: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[tuple[float, ...], ...]:
        if timeout_seconds is None:
            effective_timeout = self._settings.timeout_seconds
        else:
            if (
                type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds)
                or timeout_seconds <= 0
            ):
                raise ValueError(
                    "embedding provider timeout is invalid"
                )
            effective_timeout = min(
                self._settings.timeout_seconds,
                timeout_seconds,
            )
        if (
            not isinstance(texts, Sequence)
            or isinstance(texts, (str, bytes))
            or not texts
            or len(texts) > self._settings.max_batch_documents
            or any(
                not isinstance(text, str) or not text.strip()
                for text in texts
            )
        ):
            raise _provider_error("EMBEDDING_INVALID_INPUT") from None

        try:
            request_body = json.dumps(
                {
                    "model": self._settings.model,
                    "input": list(texts),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except UnicodeEncodeError:
            raise _provider_error(
                "EMBEDDING_INVALID_INPUT"
            ) from None
        endpoint = (
            f"{str(self._settings.base_url).rstrip('/')}"
            "/embeddings"
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
                response_body = response.read(
                    self._settings.max_response_bytes + 1
                )
        except HTTPError as error:
            code = (
                "EMBEDDING_RATE_LIMITED"
                if error.code == 429
                else "EMBEDDING_HTTP_ERROR"
            )
            raise _provider_error(code) from None
        except (TimeoutError, socket.timeout):
            raise _provider_error("EMBEDDING_TIMEOUT") from None
        except IncompleteRead:
            raise _provider_error(
                "EMBEDDING_INVALID_RESPONSE"
            ) from None
        except HTTPException:
            raise _provider_error(
                "EMBEDDING_CONNECTION_ERROR"
            ) from None
        except URLError as error:
            code = (
                "EMBEDDING_TIMEOUT"
                if _is_timeout(error)
                else "EMBEDDING_CONNECTION_ERROR"
            )
            raise _provider_error(code) from None
        except OSError:
            raise _provider_error(
                "EMBEDDING_CONNECTION_ERROR"
            ) from None

        if len(response_body) > self._settings.max_response_bytes:
            raise _provider_error(
                "EMBEDDING_INVALID_RESPONSE"
            ) from None
        try:
            envelope = json.loads(response_body.decode("utf-8"))
            if not isinstance(envelope, dict):
                raise TypeError
            response_model = envelope.get("model", self.model_id)
            if (
                not isinstance(response_model, str)
                or response_model != self.model_id
            ):
                raise TypeError
            data = envelope["data"]
            if (
                not isinstance(data, list)
                or len(data) != len(texts)
            ):
                raise TypeError

            ordered: list[tuple[float, ...] | None] = [
                None
            ] * len(texts)
            for item in data:
                if not isinstance(item, dict):
                    raise TypeError
                index = item["index"]
                vector = item["embedding"]
                if (
                    type(index) is not int
                    or index < 0
                    or index >= len(texts)
                    or ordered[index] is not None
                    or not isinstance(vector, list)
                    or len(vector) != self.dimension
                ):
                    raise TypeError

                normalized_vector: list[float] = []
                for value in vector:
                    if type(value) not in (int, float):
                        raise TypeError
                    normalized_value = float(value)
                    if not math.isfinite(normalized_value):
                        raise ValueError
                    normalized_vector.append(normalized_value)
                if not math.isfinite(
                    math.hypot(*normalized_vector)
                ) or math.hypot(*normalized_vector) == 0:
                    raise ValueError
                ordered[index] = tuple(normalized_vector)

            if any(vector is None for vector in ordered):
                raise TypeError
        except EmbeddingProviderError:
            raise
        except (
            UnicodeDecodeError,
            ValueError,
            OverflowError,
            RecursionError,
            KeyError,
            TypeError,
        ):
            raise _provider_error(
                "EMBEDDING_INVALID_RESPONSE"
            ) from None

        return tuple(
            vector
            for vector in ordered
            if vector is not None
        )
