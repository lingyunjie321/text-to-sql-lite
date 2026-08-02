"""Shared, public-safe error mapping for local Profile routes."""

from __future__ import annotations

import logging

from fastapi import HTTPException

from app.local.datasource_service import DatasourceProfileNotFoundError
from app.local.model_service import ModelProfileNotFoundError
from app.local.profile_store import (
    ProfileAlreadyExistsError,
    ProfileStoreError,
)

logger = logging.getLogger(__name__)


def profile_http_error(
    error: Exception,
    *,
    operation: str,
) -> HTTPException:
    if isinstance(error, HTTPException):
        return error
    if isinstance(error, ModelProfileNotFoundError):
        return _http_error(
            404,
            error.code,
            "The model profile was not found.",
        )
    if isinstance(error, DatasourceProfileNotFoundError):
        return _http_error(
            404,
            error.code,
            "The datasource profile was not found.",
        )
    if isinstance(error, ProfileAlreadyExistsError):
        return _http_error(
            409,
            error.code,
            "The profile already exists.",
        )
    if isinstance(error, ProfileStoreError):
        return _http_error(
            503,
            "PROFILE_STORE_UNAVAILABLE",
            "Profile storage is unavailable.",
        )
    logger.warning(
        "api_profile_unexpected_error",
        extra={
            "operation": operation,
            "error_category": "unexpected",
        },
    )
    return _http_error(
        500,
        "PROFILE_INTERNAL_ERROR",
        "The profile operation could not be completed.",
    )


def profile_service_unavailable() -> HTTPException:
    return _http_error(
        503,
        "PROFILE_SERVICE_UNAVAILABLE",
        "Profile services are unavailable.",
    )


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )
