"""Local model Profile CRUD routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status

from app.api.bootstrap import ApplicationServices, RequestIdentity
from app.api.dependencies import authenticate, services_from_request
from app.api.profile_models import (
    ModelProfileCreate,
    ProfileErrorResponse,
    ModelProfileReplace,
    ModelProfileResponse,
)
from app.api.routes._profile_common import (
    profile_http_error,
    profile_service_unavailable,
)
from app.local.model_service import ModelProfileService
from app.local.profile_models import PROFILE_ID_PATTERN

model_profiles_router = APIRouter(prefix="/api/v1/local/models")
_STORE_ERROR_RESPONSES = {
    500: {"model": ProfileErrorResponse},
    503: {"model": ProfileErrorResponse},
}
_ITEM_ERROR_RESPONSES = {
    404: {"model": ProfileErrorResponse},
    **_STORE_ERROR_RESPONSES,
}
ProfileId = Annotated[
    str,
    Path(
        min_length=1,
        max_length=64,
        pattern=PROFILE_ID_PATTERN.pattern,
    ),
]


def _service(services: ApplicationServices) -> ModelProfileService:
    service = services.model_profiles
    if service is None:
        raise profile_service_unavailable()
    return service


@model_profiles_router.post(
    "",
    response_model=ModelProfileResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ProfileErrorResponse},
        **_STORE_ERROR_RESPONSES,
    },
)
async def create_model_profile(
    request: ModelProfileCreate,
    services: Annotated[ApplicationServices, Depends(services_from_request)],
    identity: Annotated[RequestIdentity, Depends(authenticate)],
) -> ModelProfileResponse:
    del identity
    try:
        view = _service(services).create(
            request.to_profile(),
            generation_api_key=request.api_key,
            embedding_api_key=request.embedding_api_key,
        )
        return ModelProfileResponse.from_view(view)
    except Exception as error:
        raise profile_http_error(error, operation="create_model") from None


@model_profiles_router.get(
    "",
    response_model=list[ModelProfileResponse],
    responses=_STORE_ERROR_RESPONSES,
)
async def list_model_profiles(
    services: Annotated[ApplicationServices, Depends(services_from_request)],
    identity: Annotated[RequestIdentity, Depends(authenticate)],
) -> list[ModelProfileResponse]:
    del identity
    try:
        return [
            ModelProfileResponse.from_view(view)
            for view in _service(services).list()
        ]
    except Exception as error:
        raise profile_http_error(error, operation="list_models") from None


@model_profiles_router.get(
    "/{profile_id}",
    response_model=ModelProfileResponse,
    responses=_ITEM_ERROR_RESPONSES,
)
async def get_model_profile(
    profile_id: ProfileId,
    services: Annotated[ApplicationServices, Depends(services_from_request)],
    identity: Annotated[RequestIdentity, Depends(authenticate)],
) -> ModelProfileResponse:
    del identity
    try:
        return ModelProfileResponse.from_view(
            _service(services).get(profile_id)
        )
    except Exception as error:
        raise profile_http_error(error, operation="get_model") from None


@model_profiles_router.put(
    "/{profile_id}",
    response_model=ModelProfileResponse,
    responses={
        409: {"model": ProfileErrorResponse},
        **_ITEM_ERROR_RESPONSES,
    },
)
async def replace_model_profile(
    profile_id: ProfileId,
    request: ModelProfileReplace,
    services: Annotated[ApplicationServices, Depends(services_from_request)],
    identity: Annotated[RequestIdentity, Depends(authenticate)],
) -> ModelProfileResponse:
    del identity
    if request.id != profile_id:
        raise _profile_id_conflict()
    keyword_arguments: dict[str, object] = {}
    if "api_key" in request.model_fields_set:
        keyword_arguments["generation_api_key"] = request.api_key
    if "embedding_api_key" in request.model_fields_set:
        keyword_arguments["embedding_api_key"] = request.embedding_api_key
    try:
        view = _service(services).replace(
            request.to_profile(),
            **keyword_arguments,
        )
        return ModelProfileResponse.from_view(view)
    except Exception as error:
        raise profile_http_error(error, operation="replace_model") from None


@model_profiles_router.delete(
    "/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ITEM_ERROR_RESPONSES,
)
async def delete_model_profile(
    profile_id: ProfileId,
    services: Annotated[ApplicationServices, Depends(services_from_request)],
    identity: Annotated[RequestIdentity, Depends(authenticate)],
) -> Response:
    del identity
    try:
        _service(services).delete(profile_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as error:
        raise profile_http_error(error, operation="delete_model") from None


def _profile_id_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "PROFILE_ID_CONFLICT",
            "message": "The profile ID cannot be changed.",
        },
    )
