"""FastAPI application factories. HTTP concerns and wiring only; logic lives in other packages.

- ``create_app``: pure, no I/O at construction. Tests pass settings, checks and lifespan.
- ``create_production_app``: the composition root used by ``eka-api``. It opens the
  database pool on startup, registers the database readiness check and closes on shutdown.
"""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from enterprise_knowledge import __version__
from enterprise_knowledge.api import health
from enterprise_knowledge.api.health import ReadinessCheck
from enterprise_knowledge.api.middleware import RequestContextMiddleware
from enterprise_knowledge.config import Settings, get_settings
from enterprise_knowledge.infrastructure.postgres.store import PostgresDocumentStore
from enterprise_knowledge.observability.logging import configure_logging

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_app(
    settings: Settings | None = None,
    readiness_checks: dict[str, ReadinessCheck] | None = None,
    lifespan: Lifespan | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)

    app = FastAPI(title="Enterprise Knowledge AI", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.logger = logging.getLogger("enterprise_knowledge.api")
    app.state.readiness_checks = dict(readiness_checks or {})

    app.add_middleware(RequestContextMiddleware)
    app.include_router(health.router)
    return app


def create_production_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Fails fast on a wrong embedding dimension or missing migrations (ADR-0007).
        store = await PostgresDocumentStore.connect(
            settings.database_url.get_secret_value(),
            embedding_dimension=settings.embedding_dimension,
            min_size=settings.database_pool_min_size,
            max_size=settings.database_pool_max_size,
        )
        app.state.document_store = store
        app.state.readiness_checks["database"] = store.ping
        try:
            yield
        finally:
            await store.close()

    return create_app(settings, lifespan=lifespan)
