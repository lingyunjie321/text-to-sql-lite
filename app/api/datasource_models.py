"""动态数据源连接测试与 metadata HTTP 契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictInt,
    StrictStr,
    field_validator,
)

from app.connectors.catalog import DiscoveredMetadata, MetadataLimits
from app.local.datasource_runtime import DatasourceConnectionConfig
from app.local.profile_models import DatasourceProfile


class DatasourceConnectionTestRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    database_type: Literal["postgresql", "mysql"]
    host: StrictStr
    port: StrictInt = Field(ge=1, le=65535)
    database: StrictStr
    username: StrictStr
    password: SecretStr = Field(
        json_schema_extra={"writeOnly": True},
        repr=False,
    )

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        return DatasourceProfile.validate_host(value)

    @field_validator("database")
    @classmethod
    def validate_database(cls, value: str) -> str:
        return DatasourceProfile.validate_database(value)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return DatasourceProfile.validate_username(value)

    def to_config(self) -> DatasourceConnectionConfig:
        return DatasourceConnectionConfig(
            datasource_id="connection-test",
            database_type=self.database_type,
            host=self.host,
            port=self.port,
            database=self.database,
            username=self.username,
        )


class MetadataLimitsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeout_seconds: float
    max_relations: int
    max_columns: int
    max_foreign_keys: int

    @classmethod
    def from_limits(cls, limits: MetadataLimits) -> MetadataLimitsResponse:
        return cls(
            timeout_seconds=limits.timeout_seconds,
            max_relations=limits.max_relations,
            max_columns=limits.max_columns,
            max_foreign_keys=limits.max_foreign_keys,
        )


class RelationSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_name: str = Field(serialization_alias="schema")
    name: str
    kind: Literal["table", "view"]


class DatasourceConnectionTestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"] = "ok"
    schemas: tuple[str, ...]
    relations: tuple[RelationSummaryResponse, ...]
    truncated: bool
    limits: MetadataLimitsResponse

    @classmethod
    def from_discovered(
        cls,
        discovered: DiscoveredMetadata,
        *,
        limits: MetadataLimits,
    ) -> DatasourceConnectionTestResponse:
        return cls(
            schemas=discovered.snapshot.schemas,
            relations=tuple(
                RelationSummaryResponse(
                    schema_name=relation.schema_name,
                    name=relation.relation_name,
                    kind=relation.relation_kind,
                )
                for relation in discovered.relations
            ),
            truncated=discovered.truncated,
            limits=MetadataLimitsResponse.from_limits(limits),
        )


class MetadataColumnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    data_type: str
    nullable: bool


class MetadataRelationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    kind: Literal["table", "view"]
    columns: tuple[MetadataColumnResponse, ...]
    primary_key: tuple[str, ...]


class MetadataSchemaResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    relations: tuple[MetadataRelationResponse, ...]


class MetadataForeignKeyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    source_schema: str
    source_table: str
    source_columns: tuple[str, ...]
    target_schema: str
    target_table: str
    target_columns: tuple[str, ...]


class DatasourceMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    datasource_id: str
    schemas: tuple[MetadataSchemaResponse, ...]
    foreign_keys: tuple[MetadataForeignKeyResponse, ...]
    truncated: bool
    limits: MetadataLimitsResponse

    @classmethod
    def from_discovered(
        cls,
        datasource_id: str,
        discovered: DiscoveredMetadata,
        *,
        limits: MetadataLimits,
    ) -> DatasourceMetadataResponse:
        snapshot = discovered.snapshot
        primary_keys = {
            (key.schema_name, key.table_name): key.columns
            for key in snapshot.primary_keys
        }
        schemas = tuple(
            MetadataSchemaResponse(
                name=schema_name,
                relations=tuple(
                    MetadataRelationResponse(
                        name=table.table_name,
                        kind=(
                            "view"
                            if table.relation_kind == "view"
                            else "table"
                        ),
                        columns=tuple(
                            MetadataColumnResponse(
                                name=column.column_name,
                                data_type=column.formatted_type,
                                nullable=column.nullable,
                            )
                            for column in table.columns
                        ),
                        primary_key=primary_keys.get(
                            (table.schema_name, table.table_name),
                            (),
                        ),
                    )
                    for table in snapshot.tables
                    if table.schema_name == schema_name
                ),
            )
            for schema_name in snapshot.schemas
        )
        foreign_keys = tuple(
            MetadataForeignKeyResponse(
                name=foreign_key.constraint_name,
                source_schema=foreign_key.source_schema,
                source_table=foreign_key.source_table,
                source_columns=foreign_key.source_columns,
                target_schema=foreign_key.target_schema,
                target_table=foreign_key.target_table,
                target_columns=foreign_key.target_columns,
            )
            for foreign_key in snapshot.foreign_keys
        )
        return cls(
            datasource_id=datasource_id,
            schemas=schemas,
            foreign_keys=foreign_keys,
            truncated=discovered.truncated,
            limits=MetadataLimitsResponse.from_limits(limits),
        )
