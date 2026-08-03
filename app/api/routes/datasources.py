"""Local datasource Profile CRUD routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status

from app.api.bootstrap import ApplicationServices, RequestIdentity
from app.api.datasource_models import (
    DatasourceConnectionTestRequest,
    DatasourceConnectionTestResponse,
    DatasourceMetadataResponse,
)
from app.api.dependencies import authenticate, services_from_request
from app.api.profile_models import (
    DatasourceProfileCreate,
    DatasourceProfileReplace,
    DatasourceProfileResponse,
    ProfileErrorResponse,
)
from app.api.routes._profile_common import (
    profile_http_error,
    profile_service_unavailable,
)
from app.connectors.catalog import MetadataLimits
from app.local.datasource_service import DatasourceProfileService
from app.local.profile_models import PROFILE_ID_PATTERN

datasource_profiles_router = APIRouter(prefix="/api/v1/local/datasources")
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


def _service(services: ApplicationServices) -> DatasourceProfileService:
    service = services.datasource_profiles
    if service is None:
        raise profile_service_unavailable()
    return service


def _runtime_service(services: ApplicationServices):
    service = services.datasource_runtime_service
    if service is None:
        raise profile_service_unavailable()
    return service


@datasource_profiles_router.post(
    "/test",
    response_model=DatasourceConnectionTestResponse,
    responses={
        409: {"model": ProfileErrorResponse},
        504: {"model": ProfileErrorResponse},
        **_STORE_ERROR_RESPONSES,
    },
)
async def test_datasource_connection(
    request: DatasourceConnectionTestRequest,
    services: Annotated[ApplicationServices, Depends(services_from_request)],
    identity: Annotated[RequestIdentity, Depends(authenticate)],
) -> DatasourceConnectionTestResponse:
    del identity
    try:
        discovered = _runtime_service(services).test_connection(
            request.to_config(),
            request.password,
        )
        return DatasourceConnectionTestResponse.from_discovered(
            discovered,
            limits=MetadataLimits(),
        )
    except Exception as error:
        raise profile_http_error(error, operation="test_datasource") from None


@datasource_profiles_router.post(
    "",
    response_model=DatasourceProfileResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ProfileErrorResponse},
        504: {"model": ProfileErrorResponse},
        **_STORE_ERROR_RESPONSES,
    },
)
async def create_datasource_profile(
    request: DatasourceProfileCreate,
    services: Annotated[ApplicationServices, Depends(services_from_request)],
    identity: Annotated[RequestIdentity, Depends(authenticate)],
) -> DatasourceProfileResponse:
    del identity
    try:
        view = _service(services).create(
            request.to_profile(),
            password=request.password,
        )
        return DatasourceProfileResponse.from_view(view)
    except Exception as error:
        raise profile_http_error(error, operation="create_datasource") from None


@datasource_profiles_router.get(
    "",
    response_model=list[DatasourceProfileResponse],
    responses=_STORE_ERROR_RESPONSES,
)
async def list_datasource_profiles(
    services: Annotated[ApplicationServices, Depends(services_from_request)],
    identity: Annotated[RequestIdentity, Depends(authenticate)],
) -> list[DatasourceProfileResponse]:
    del identity
    try:
        return [
            DatasourceProfileResponse.from_view(view)
            for view in _service(services).list()
        ]
    except Exception as error:
        raise profile_http_error(error, operation="list_datasources") from None


@datasource_profiles_router.get(
    "/{profile_id}",
    response_model=DatasourceProfileResponse,
    responses=_ITEM_ERROR_RESPONSES,
)
async def get_datasource_profile(
    profile_id: ProfileId,
    services: Annotated[ApplicationServices, Depends(services_from_request)],
    identity: Annotated[RequestIdentity, Depends(authenticate)],
) -> DatasourceProfileResponse:
    del identity
    try:
        return DatasourceProfileResponse.from_view(
            _service(services).get(profile_id)
        )
    except Exception as error:
        raise profile_http_error(error, operation="get_datasource") from None


@datasource_profiles_router.get(
    "/{profile_id}/metadata",
    response_model=DatasourceMetadataResponse,
    responses={
        404: {"model": ProfileErrorResponse},
        409: {"model": ProfileErrorResponse},
        504: {"model": ProfileErrorResponse},
        **_STORE_ERROR_RESPONSES,
    },
)
async def get_datasource_metadata(
    profile_id: ProfileId,
    services: Annotated[ApplicationServices, Depends(services_from_request)],
    identity: Annotated[RequestIdentity, Depends(authenticate)],
) -> DatasourceMetadataResponse:
    del identity
    try:
        discovered = _service(services).discover_metadata(profile_id)
        return DatasourceMetadataResponse.from_discovered(
            profile_id,
            discovered,
            limits=MetadataLimits(),
        )
    except Exception as error:
        raise profile_http_error(error, operation="get_metadata") from None


@datasource_profiles_router.put(
    "/{profile_id}",
    response_model=DatasourceProfileResponse,
    responses={
        409: {"model": ProfileErrorResponse},
        504: {"model": ProfileErrorResponse},
        **_ITEM_ERROR_RESPONSES,
    },
)
async def replace_datasource_profile(
    profile_id: ProfileId,
    request: DatasourceProfileReplace,
    services: Annotated[ApplicationServices, Depends(services_from_request)],
    identity: Annotated[RequestIdentity, Depends(authenticate)],
) -> DatasourceProfileResponse:
    del identity
    if request.id != profile_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROFILE_ID_CONFLICT",
                "message": "The profile ID cannot be changed.",
            },
        )
    keyword_arguments: dict[str, object] = {}
    if "password" in request.model_fields_set:
        keyword_arguments["password"] = request.password
    try:
        view = _service(services).replace(
            request.to_profile(),
            **keyword_arguments,
        )
        return DatasourceProfileResponse.from_view(view)
    except Exception as error:
        raise profile_http_error(error, operation="replace_datasource") from None


@datasource_profiles_router.delete(
    "/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ITEM_ERROR_RESPONSES,
)
async def delete_datasource_profile(
    profile_id: ProfileId,
    services: Annotated[ApplicationServices, Depends(services_from_request)],
    identity: Annotated[RequestIdentity, Depends(authenticate)],
) -> Response:
    del identity
    try:
        _service(services).delete(profile_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as error:
        raise profile_http_error(error, operation="delete_datasource") from None
