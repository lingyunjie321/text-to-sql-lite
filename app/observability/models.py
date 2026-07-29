from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.connectors.errors import ErrorType
from app.reflection import RepairStrategy
from app.workflow import FinalStatus


class TraceNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node: str = Field(min_length=1)
    duration_ms: float = Field(ge=0)
    attempt_number: int | None = Field(default=None, ge=0)
    route: str | None = Field(default=None, min_length=1)


class TraceAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_number: int = Field(ge=0, le=3)
    fingerprint: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    validation_passed: bool | None = None
    execution_succeeded: bool = False
    error_type: ErrorType | None = None
    database_duration_ms: float | None = Field(default=None, ge=0)


class TraceGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    call_number: int = Field(ge=1, le=4)
    attempt_number: int = Field(ge=0, le=3)
    model_config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_contract_version: str = Field(min_length=1)
    effective_contract_version: str = Field(min_length=1)
    repair_strategy: RepairStrategy | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class TraceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    final_status: FinalStatus
    error_type: ErrorType | None = None
    error_code: str | None = Field(default=None, min_length=1)
    schema_version: str | None = Field(default=None, min_length=1)
    repair_count: int = Field(ge=0, le=3)
    infrastructure_retry_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    database_duration_ms: float | None = Field(default=None, ge=0)
    returned_row_count: int = Field(ge=0, le=1000)
    truncated: bool = False
    nodes: tuple[TraceNode, ...] = ()
    attempts: tuple[TraceAttempt, ...] = ()
    generations: tuple[TraceGeneration, ...] = ()
