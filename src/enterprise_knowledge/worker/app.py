"""Composition root of the ingestion worker (``eka-worker``, JOB-01, ADR-0016)."""

import asyncio
import logging
import signal
from contextlib import AsyncExitStack

from enterprise_knowledge.config import Settings
from enterprise_knowledge.infrastructure.blobs import LocalBlobStore
from enterprise_knowledge.infrastructure.postgres.jobs import PostgresJobStore
from enterprise_knowledge.infrastructure.postgres.store import PostgresDocumentStore
from enterprise_knowledge.infrastructure.providers import build_embedder
from enterprise_knowledge.ingestion.jobs import ProcessIngestionJob
from enterprise_knowledge.ingestion.limits import IngestionLimits
from enterprise_knowledge.observability.logging import configure_logging
from enterprise_knowledge.worker.loop import IngestionWorker

logger = logging.getLogger(__name__)


async def build_worker(settings: Settings, stack: AsyncExitStack) -> IngestionWorker:
    """Wire the worker to Postgres, the blob store and the embedder; ``stack`` closes them."""
    # Fails fast on a wrong embedding dimension or missing migrations (ADR-0007).
    store = await PostgresDocumentStore.connect(
        settings.database_url.get_secret_value(),
        embedding_dimension=settings.embedding_dimension,
        min_size=1,
        max_size=2,
    )
    stack.push_async_callback(store.close)
    jobs = await PostgresJobStore.connect(
        settings.database_url.get_secret_value(),
        visibility_seconds=settings.job_visibility_seconds,
    )
    stack.push_async_callback(jobs.close)
    process = ProcessIngestionJob(
        documents=store,
        jobs=jobs,
        blobs=LocalBlobStore(settings.blob_dir),
        embedder=build_embedder(settings, stack),
        limits=IngestionLimits(max_bytes=settings.max_upload_bytes),
    )
    return IngestionWorker(
        queue=jobs,
        process=process,
        wait_seconds=settings.worker_wait_seconds,
        retry_base_seconds=settings.job_retry_base_seconds,
        retry_max_seconds=settings.job_retry_max_seconds,
    )


async def run(settings: Settings) -> None:
    """Run until SIGTERM or SIGINT; the job in hand is finished before exiting."""
    configure_logging(settings.log_level, json_output=settings.log_json)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    async with AsyncExitStack() as stack:
        worker = await build_worker(settings, stack)
        await worker.run(stop)
