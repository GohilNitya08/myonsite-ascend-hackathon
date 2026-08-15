"""FastAPI application entry point."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings

logger = logging.getLogger(__name__)


def create_application() -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings.app_env.lower() == "development":
        logger.info(
            "Development database configuration: host=%s port=%s name=%s user=%s env_file_loaded=%s",
            settings.mysql_host,
            settings.mysql_port,
            settings.mysql_database,
            settings.mysql_user,
            settings.env_file_loaded,
        )

    application = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        version="0.1.0",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(api_router, prefix=settings.api_v1_prefix)

    @application.get("/", tags=["system"])
    def root() -> dict[str, str]:
        """Provide a small discovery endpoint for the service."""
        return {"message": f"Welcome to {settings.app_name}"}

    return application


app = create_application()
