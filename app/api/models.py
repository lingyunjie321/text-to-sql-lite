from __future__ import annotations

from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
    model_validator,
)

from app.connectors.errors import ErrorType
from app.workflow import FinalStatus

QUESTION_MAX_CHARS = 2000

type JsonValue = (
    None
    | bool
    | int
    | float
    | str
    | list[JsonValue]
    | dict[str, JsonValue]
)


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: StrictStr
    datasource_id: StrictStr = "pagila"
    schemas: tuple[StrictStr, ...] = ()
    debug: StrictBool = False

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        if not value.strip() or len(value.strip()) > QUESTION_MAX_CHARS:
            raise ValueError("question is invalid")
        return value

    @field_validator("datasource_id")
    @classmethod
    def validate_datasource_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("datasource_id is invalid")
        return stripped

    @field_validator("schemas")
    @classmethod
    def validate_schemas(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        stripped = tuple(schema.strip() for schema in value)
        if any(not schema for schema in stripped):
            raise ValueError("schemas are invalid")
        return stripped


class ResponseColumn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    type_oid: int = Field(ge=0)


class ResponseClarification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    question: str = Field(min_length=1)


class PublicError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    error_type: ErrorType
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class QueryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    status: FinalStatus
    sql: str | None = None
    columns: tuple[ResponseColumn, ...] = ()
    rows: list[list[JsonValue]] = Field(default_factory=list)
    returned_row_count: int = Field(default=0, ge=0, le=1000)
    truncated: bool = False
    attempts: int = Field(default=0, ge=0, le=4)
    repair_count: int = Field(default=0, ge=0, le=3)
    clarification: ResponseClarification | None = None
    error: PublicError | None = None

    @field_validator("sql")
    @classmethod
    def strip_sql(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("response SQL is invalid")
        return stripped

    @model_validator(mode="after")
    def validate_terminal_payload(self) -> Self:
        success = self.status in {
            FinalStatus.SUCCEEDED_FIRST_PASS,
            FinalStatus.SUCCEEDED_REPAIRED,
        }
        if success:
            valid = (
                self.sql is not None
                and self.error is None
                and self.clarification is None
                and self.returned_row_count == len(self.rows)
                and self.attempts == self.repair_count + 1
                and (
                    (
                        self.status
                        == FinalStatus.SUCCEEDED_FIRST_PASS
                        and self.repair_count == 0
                    )
                    or (
                        self.status
                        == FinalStatus.SUCCEEDED_REPAIRED
                        and self.repair_count > 0
                    )
                )
            )
        elif self.status == FinalStatus.CLARIFICATION_REQUIRED:
            valid = (
                self.sql is None
                and not self.columns
                and not self.rows
                and self.returned_row_count == 0
                and self.truncated is False
                and self.clarification is not None
                and self.error is None
            )
        else:
            expected_errors = {
                FinalStatus.REJECTED_SECURITY: ErrorType.PERMISSION_DENIED,
                FinalStatus.FAILED_DUPLICATE_LOOP: ErrorType.DUPLICATE_SQL,
                FinalStatus.FAILED_TIMEOUT: ErrorType.TIMEOUT,
                FinalStatus.FAILED_CONNECTION: ErrorType.CONNECTION_ERROR,
                FinalStatus.FAILED_RESOURCE_RISK: ErrorType.RESOURCE_RISK,
            }
            if self.status == FinalStatus.FAILED_REPAIR_EXHAUSTED:
                error_matches = (
                    self.error is not None
                    and self.error.error_type
                    in {
                        ErrorType.SYNTAX_ERROR,
                        ErrorType.SCHEMA_ERROR,
                        ErrorType.DIALECT_ERROR,
                    }
                    and self.repair_count == 3
                )
            elif self.status == FinalStatus.FAILED_INTERNAL:
                error_matches = (
                    self.error is not None
                    and self.error.error_type
                    not in {
                        ErrorType.PERMISSION_DENIED,
                        ErrorType.DUPLICATE_SQL,
                        ErrorType.TIMEOUT,
                        ErrorType.CONNECTION_ERROR,
                        ErrorType.RESOURCE_RISK,
                    }
                    and not (
                        self.error.error_type
                        in {
                            ErrorType.SYNTAX_ERROR,
                            ErrorType.SCHEMA_ERROR,
                            ErrorType.DIALECT_ERROR,
                        }
                        and self.repair_count == 3
                    )
                )
            else:
                error_matches = (
                    self.error is not None
                    and self.error.error_type
                    == expected_errors.get(self.status)
                )
            valid = (
                self.sql is None
                and not self.columns
                and not self.rows
                and self.returned_row_count == 0
                and self.truncated is False
                and self.clarification is None
                and error_matches
            )
        if not valid:
            raise ValueError("query response terminal payload is invalid")
        return self
