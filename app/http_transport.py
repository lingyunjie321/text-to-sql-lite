from typing import Protocol
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)


class HTTPResponse(Protocol):
    def __enter__(self) -> "HTTPResponse": ...

    def __exit__(self, *args: object) -> object: ...

    def read(self, amount: int = -1) -> bytes: ...


class HTTPTransport(Protocol):
    def open(
        self,
        request: Request,
        *,
        timeout: float,
    ) -> HTTPResponse: ...


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
    ) -> HTTPResponse:
        return self._opener.open(  # type: ignore[return-value]
            request,
            timeout=timeout,
        )
