"""Shared FastAPI request dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.bootstrap import (
    ApplicationServices,
    RequestIdentity,
    default_request_identity,
)
from app.config import load_auth_settings

_bearer_scheme = HTTPBearer(auto_error=False)


def authenticate(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer_scheme),
    ],
) -> RequestIdentity:
    auth = load_auth_settings()
    if auth.api_key_value is None:
        return default_request_identity()
    if credentials is None:
        raise HTTPException(status_code=401, detail="API key required")
    if credentials.credentials != auth.api_key_value:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return RequestIdentity(
        subject="api-key-user",
        can_debug=(
            auth.debug_key_value is not None
            and credentials.credentials == auth.debug_key_value
        ),
    )


def services_from_request(request: Request) -> ApplicationServices:
    services = getattr(request.app.state, "services", None)
    if not isinstance(services, ApplicationServices):
        raise RuntimeError("application services are unavailable")
    return services
