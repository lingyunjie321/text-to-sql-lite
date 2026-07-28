"""FastAPI contracts for the Text-to-SQL MVP."""

from app.api.application import API_PATH, create_app
from app.api.bootstrap import (
    PAGILA_MVP_ALLOWED_SCHEMAS,
    PAGILA_MVP_ALLOWED_TABLES,
    ApplicationServices,
    RequestIdentity,
    build_production_services,
    default_request_identity,
)
from app.api.models import (
    QUESTION_MAX_CHARS,
    PublicError,
    QueryRequest,
    QueryResponse,
    ResponseClarification,
    ResponseColumn,
)
from app.api.response import build_query_response

__all__ = [
    "API_PATH",
    "PAGILA_MVP_ALLOWED_SCHEMAS",
    "PAGILA_MVP_ALLOWED_TABLES",
    "ApplicationServices",
    "QUESTION_MAX_CHARS",
    "PublicError",
    "QueryRequest",
    "QueryResponse",
    "RequestIdentity",
    "ResponseClarification",
    "ResponseColumn",
    "build_query_response",
    "build_production_services",
    "create_app",
    "default_request_identity",
]
