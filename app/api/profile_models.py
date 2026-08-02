"""HTTP request and response models for local Profile CRUD."""

from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictStr,
    field_validator,
)

from app.local.datasource_service import DatasourceProfileView
from app.local.model_service import ModelProfileView
from app.local.profile_models import DatasourceProfile, ModelProfile


class ProfileErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: StrictStr
    message: StrictStr


class ProfileErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    detail: ProfileErrorDetail


class ModelProfileCreate(ModelProfile):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    api_key: SecretStr | None = Field(
        default=None,
        json_schema_extra={"writeOnly": True},
        repr=False,
    )
    embedding_api_key: SecretStr | None = Field(
        default=None,
        json_schema_extra={"writeOnly": True},
        repr=False,
    )

    @field_validator("api_key", "embedding_api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        raw_value = value.get_secret_value()
        if (
            not raw_value
            or raw_value != raw_value.strip()
            or any(
                not 33 <= ord(character) <= 126
                for character in raw_value
            )
        ):
            raise ValueError("api key is invalid")
        return value

    def to_profile(self) -> ModelProfile:
        return ModelProfile.model_validate(
            self.model_dump(exclude={"api_key", "embedding_api_key"})
        )


class ModelProfileReplace(ModelProfileCreate):
    pass


class ModelProfileResponse(ModelProfile):
    generation_credential_status: Literal["configured", "missing"]
    embedding_credential_status: Literal[
        "configured",
        "missing",
        "not_applicable",
    ]

    @classmethod
    def from_view(cls, view: ModelProfileView) -> ModelProfileResponse:
        return cls(
            **view.profile.model_dump(),
            generation_credential_status=view.generation_credential_status,
            embedding_credential_status=view.embedding_credential_status,
        )


class DatasourceProfileCreate(DatasourceProfile):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    password: SecretStr | None = Field(
        default=None,
        json_schema_extra={"writeOnly": True},
        repr=False,
    )

    def to_profile(self) -> DatasourceProfile:
        return DatasourceProfile.model_validate(
            self.model_dump(exclude={"password"})
        )


class DatasourceProfileReplace(DatasourceProfileCreate):
    pass


class DatasourceProfileResponse(DatasourceProfile):
    password_status: Literal["configured", "missing"]

    @classmethod
    def from_view(
        cls,
        view: DatasourceProfileView,
    ) -> DatasourceProfileResponse:
        return cls(
            **view.profile.model_dump(),
            password_status=view.password_status,
        )
