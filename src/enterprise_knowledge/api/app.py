"""FastAPI application factories. HTTP concerns and wiring only; logic lives in other packages.

- ``create_app``: pure, no I/O at construction. Tests pass settings, checks and lifespan.
- ``create_production_app``: the composition root used by ``eka-api``. It opens the
  database pool on startup, registers the database readiness check and closes on shutdown.
"""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

from enterprise_knowledge import __version__
from enterprise_knowledge.agents.modes import AnswerModes
from enterprise_knowledge.agents.workflow import AnswerWorkflow, WorkflowLimits
from enterprise_knowledge.api import health
from enterprise_knowledge.api.errors import install_error_handlers
from enterprise_knowledge.api.health import ReadinessCheck
from enterprise_knowledge.api.middleware import RequestContextMiddleware
from enterprise_knowledge.api.routes import answers, documents, jobs
from enterprise_knowledge.api.services import Services
from enterprise_knowledge.config import Settings, get_settings
from enterprise_knowledge.domain.ports import ChatModel, Embedder
from enterprise_knowledge.generation.answer import AnswerQuestion
from enterprise_knowledge.infrastructure.blobs import LocalBlobStore
from enterprise_knowledge.infrastructure.postgres.jobs import PostgresJobStore
from enterprise_knowledge.infrastructure.postgres.store import PostgresDocumentStore
from enterprise_knowledge.infrastructure.providers import build_chat_model, build_embedder
from enterprise_knowledge.ingestion.delete import DeleteDocument
from enterprise_knowledge.ingestion.jobs import SubmitDocument
from enterprise_knowledge.ingestion.limits import IngestionLimits
from enterprise_knowledge.observability.logging import configure_logging
from enterprise_knowledge.retrieval.search import RetrievalSettings, SearchKnowledge

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
    app.include_router(jobs.router)
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
            jobs = await PostgresJobStore.connect(
                settings.database_url.get_secret_value(),
                visibility_seconds=settings.job_visibility_seconds,
            )
            stack.push_async_callback(jobs.close)
            app.state.services = build_services(
                settings,
                store,
                jobs,
                embedder=build_embedder(settings, stack),
                chat=build_chat_model(settings, stack),
            )
            yield

    return create_app(settings, lifespan=lifespan)


def build_services(
    settings: Settings,
    store: PostgresDocumentStore,
    jobs: PostgresJobStore,
    *,
    embedder: Embedder,
    chat: ChatModel | None,
) -> Services:
    """Wire use cases to adapters. Without a chat model, /v1/answers returns 503."""
    blobs = LocalBlobStore(settings.blob_dir)
    search = SearchKnowledge(
        search=store,
        embedder=embedder,
        retrieval=RetrievalSettings(
            mode=settings.retrieval_mode,
            rrf_k=settings.rrf_k,
            candidates=settings.hybrid_candidates,
        ),
    )
    answer = None
    if chat is not None:
        answer = AnswerModes(
            direct=AnswerQuestion(
                search=search,
                chat=chat,
                k=settings.answer_top_k,
                min_score=settings.answer_min_score,
                timeout_seconds=settings.answer_timeout_seconds,
            ),
            workflow=AnswerWorkflow(
                search=search,
                chat=chat,
                limits=WorkflowLimits(
                    max_sub_questions=settings.workflow_max_sub_questions,
                    k_per_question=settings.answer_top_k,
                    max_evidence=settings.workflow_max_evidence,
                    max_steps=settings.workflow_max_sub_questions + 2,
                    timeout_seconds=settings.workflow_timeout_seconds,
                ),
                min_score=settings.answer_min_score,
            ),
        )
    return Services(
        documents=store,
        submit=SubmitDocument(
            documents=store,
            jobs=jobs,
            queue=jobs,
            blobs=blobs,
            max_attempts=settings.job_max_attempts,
            limits=IngestionLimits(max_bytes=settings.max_upload_bytes),
        ),
        jobs=jobs,
        delete=DeleteDocument(documents=store, blobs=blobs),
        search=search,
        max_upload_bytes=settings.max_upload_bytes,
        answer=answer,
        default_answer_mode=settings.answer_mode,
    )
