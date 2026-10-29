"""FastAPI application factory. HTTP concerns only; business logic lives in other packages."""

import logging

from fastapi import FastAPI

from enterprise_knowledge import __version__
from enterprise_knowledge.api import health
from enterprise_knowledge.api.health import ReadinessCheck
from enterprise_knowledge.api.middleware import RequestContextMiddleware
from enterprise_knowledge.config import Settings, get_settings
from enterprise_knowledge.observability.logging import configure_logging


def create_app(
    settings: Settings | None = None,
    readiness_checks: dict[str, ReadinessCheck] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)

    app = FastAPI(title="Enterprise Knowledge AI", version=__version__)
    app.state.settings = settings
    app.state.logger = logging.getLogger("enterprise_knowledge.api")
    app.state.readiness_checks = readiness_checks or {}

    app.add_middleware(RequestContextMiddleware)
    app.include_router(health.router)
    return app
