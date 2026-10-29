"""FastAPI application factories. HTTP concerns and wiring only; logic lives in other packages.

- ``create_app``: pure, no I/O at construction. Tests pass settings, checks and lifespan.
- ``create_production_app``: the composition root used by ``eka-api``. It opens the
  database pool on startup, registers the database readiness check and closes on shutdown.
"""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from pydantic import SecretStr

from enterprise_knowledge import __version__
from enterprise_knowledge.api import health
from enterprise_knowledge.api.errors import install_error_handlers
from enterprise_knowledge.api.health import ReadinessCheck
from enterprise_knowledge.api.middleware import RequestContextMiddleware
from enterprise_knowledge.api.routes import answers, documents
from enterprise_knowledge.api.services import Services
from enterprise_knowledge.config import Settings, get_settings
from enterprise_knowledge.domain.ports import ChatModel, Embedder
from enterprise_knowledge.generation.answer import AnswerQuestion
from enterprise_knowledge.infrastructure.blobs import LocalBlobStore
from enterprise_knowledge.infrastructure.embeddings.hashing import HashingEmbedder
from enterprise_knowledge.infrastructure.fpt.chat import FptChatModel
from enterprise_knowledge.infrastructure.fpt.client import FptClient, RetryPolicy
from enterprise_knowledge.infrastructure.fpt.embeddings import FptEmbedder
from enterprise_knowledge.infrastructure.postgres.store import PostgresDocumentStore
from enterprise_knowledge.ingestion.delete import DeleteDocument
from enterprise_knowledge.ingestion.ingest import IngestDocument
from enterprise_knowledge.ingestion.limits import IngestionLimits
from enterprise_knowledge.observability.logging import configure_logging
from enterprise_knowledge.retrieval.search import SearchKnowledge

logger = logging.getLogger(__name__)

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_app(
    settings: Settings | None = None,
    readiness_checks: dict[str, ReadinessCheck] | None = None,
    lifespan: Lifespan | None = None,
    services: Services | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)

    app = FastAPI(title="Enterprise Knowledge AI", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.logger = logging.getLogger("enterprise_knowledge.api")
    app.state.readiness_checks = dict(readiness_checks or {})
    app.state.services = services

    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(answers.router)
    return app


def create_production_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            # Fails fast on a wrong embedding dimension or missing migrations (ADR-0007).
            store = await PostgresDocumentStore.connect(
                settings.database_url.get_secret_value(),
                embedding_dimension=settings.embedding_dimension,
                min_size=settings.database_pool_min_size,
                max_size=settings.database_pool_max_size,
            )
            stack.push_async_callback(store.close)
            app.state.readiness_checks["database"] = store.ping
            app.state.services = build_services(
                settings,
                store,
                embedder=_embedder(settings, stack),
                chat=_chat_model(settings, stack),
            )
            yield

    return create_app(settings, lifespan=lifespan)


def build_services(
    settings: Settings,
    store: PostgresDocumentStore,
    *,
    embedder: Embedder,
    chat: ChatModel | None,
) -> Services:
    """Wire use cases to adapters. Without a chat model, /v1/answers returns 503."""
    blobs = LocalBlobStore(settings.blob_dir)
    search = SearchKnowledge(search=store, embedder=embedder)
    answer = None
    if chat is not None:
        answer = AnswerQuestion(
            search=search,
            chat=chat,
            k=settings.answer_top_k,
            min_score=settings.answer_min_score,
            timeout_seconds=settings.answer_timeout_seconds,
        )
    return Services(
        documents=store,
        ingest=IngestDocument(
            documents=store,
            embedder=embedder,
            blobs=blobs,
            limits=IngestionLimits(max_bytes=settings.max_upload_bytes),
        ),
        delete=DeleteDocument(documents=store, blobs=blobs),
        search=search,
        max_upload_bytes=settings.max_upload_bytes,
        answer=answer,
    )


def _embedder(settings: Settings, stack: AsyncExitStack) -> Embedder:
    """The hashing embedder is dev-only; settings refuse it outside local and test."""
    api_key = settings.embedding_api_key
    if settings.embedding_provider == "hashing" or api_key is None:  # fpt requires a key
        return HashingEmbedder(dimension=settings.embedding_dimension)
    client = _fpt_client(
        settings.embedding_base_url,
        api_key,
        settings.embedding_request_timeout_seconds,
        settings,
        stack,
    )
    return FptEmbedder(
        client, model=settings.embedding_model, dimension=settings.embedding_dimension
    )


def _chat_model(settings: Settings, stack: AsyncExitStack) -> ChatModel | None:
    api_key, model = settings.llm_api_key, settings.llm_model
    if api_key is None or model is None:  # Settings require both or neither
        logger.info("no chat model configured; /v1/answers is disabled")
        return None
    client = _fpt_client(
        settings.llm_base_url, api_key, settings.llm_request_timeout_seconds, settings, stack
    )
    return FptChatModel(client, model=model, json_mode=settings.llm_json_mode)


def _fpt_client(
    base_url: str,
    api_key: SecretStr,
    timeout_seconds: float,
    settings: Settings,
    stack: AsyncExitStack,
) -> FptClient:
    client = FptClient.create(
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        retry=RetryPolicy(max_attempts=settings.model_max_attempts),
    )
    stack.push_async_callback(client.aclose)
    return client
