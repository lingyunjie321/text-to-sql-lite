from dataclasses import dataclass
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    field_validator,
    model_validator,
)

from app.connectors.metadata import SchemaSnapshot
from app.connectors.errors import ErrorType
from app.schema_linking import SchemaLinkingResult

PROMPT_VERSION = "mvp-v1-projection-alias-view-semantics-v1"


class GeneratedSQL(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sql: str | None = None
    clarification_reason: str | None = None

    @field_validator("sql", "clarification_reason")
    @classmethod
    def strip_non_empty_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("generated value cannot be empty")
        return stripped

    @model_validator(mode="after")
    def require_exactly_one_output(self) -> Self:
        if (self.sql is None) == (self.clarification_reason is None):
            raise ValueError(
                "exactly one generated output is required"
            )
        return self


@dataclass(frozen=True, slots=True)
class GenerationContext:
    question: str
    normalized_question: str | None
    normalized_time: str | None
    dialect: str
    schema_linking: SchemaLinkingResult
    snapshot: SchemaSnapshot
    max_result_rows: int = 1000


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: Literal["system", "user"]
    content: str


@dataclass(frozen=True, slots=True)
class GenerationResult:
    output: GeneratedSQL
    input_tokens: int
    output_tokens: int
    model: str
    prompt_version: str

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("token counts cannot be negative")
        if not self.model.strip() or not self.prompt_version.strip():
            raise ValueError("generation metadata cannot be empty")


@dataclass(frozen=True, slots=True)
class LLMError:
    error_type: ErrorType
    code: str
    retryable: bool
    public_message: str


class LLMProviderError(RuntimeError):
    def __init__(self, details: LLMError) -> None:
        super().__init__(details.public_message)
        self.details = details
