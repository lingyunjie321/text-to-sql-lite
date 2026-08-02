"""API routers registered by the application factory."""

from app.api.routes.datasources import datasource_profiles_router
from app.api.routes.models import model_profiles_router
from app.api.routes.query import API_PATH, create_query_router
from app.api.routes.system import system_router

__all__ = [
    "API_PATH",
    "create_query_router",
    "datasource_profiles_router",
    "model_profiles_router",
    "system_router",
]
