"""Receive ingestion messages, process each job, requeue retries with backoff, ack (ADR-0016).

A message is acked only after its job's new state is stored, so a crash at any point leaves
the message to be redelivered when its lease runs out. ``ProcessIngestionJob`` records
every failure it can classify; anything that escapes it (for example the database being
down) is logged and the message is left unacked for redelivery.
"""

import asyncio
import contextlib
import logging
import random
from collections.abc import Awaitable, Callable

from enterprise_knowledge.domain.ids import JobId
from enterprise_knowledge.domain.jobs import IngestionJob, JobStatus
from enterprise_knowledge.domain.ports import JobQueue, QueueMessage
from enterprise_knowledge.observability.logging import request_id_var

logger = logging.getLogger(__name__)

Process = Callable[[JobId], Awaitable[IngestionJob | None]]


def retry_delay(attempts: int, *, base_seconds: float, max_seconds: float, jitter: float) -> float:
    """Exponential backoff after ``attempts`` failed attempts, capped, scaled by ``jitter``.

    ``jitter`` in [0.5, 1] keeps retries of many jobs that failed together from aligning."""
    return float(min(max_seconds, base_seconds * 2.0 ** max(attempts - 1, 0)) * jitter)


class IngestionWorker:
    def __init__(
        self,
        *,
        queue: JobQueue,
        process: Process,
        batch_size: int = 1,
        wait_seconds: float = 10.0,
        idle_sleep_seconds: float = 1.0,
        retry_base_seconds: float = 10.0,
        retry_max_seconds: float = 300.0,
        jitter: Callable[[], float] = lambda: random.uniform(0.5, 1.0),  # noqa: S311 - not crypto
    ) -> None:
        self._queue = queue
        self._process = process
        self._batch_size = batch_size
        self._wait = wait_seconds
        self._idle_sleep = idle_sleep_seconds
        self._retry_base = retry_base_seconds
        self._retry_max = retry_max_seconds
        self._jitter = jitter

    async def run(self, stop: asyncio.Event) -> None:
        """Process messages until ``stop`` is set; the message in hand is finished first."""
        logger.info("ingestion worker started")
        while not stop.is_set():
            try:
                handled = await self.run_once()
            except Exception:
                logger.exception("ingestion worker poll failed")
                handled = 0
            if not handled:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=self._idle_sleep)
        logger.info("ingestion worker stopped")

    async def run_once(self) -> int:
        """Handle one batch; returns how many messages were received."""
        messages = await self._queue.receive(max_messages=self._batch_size, wait_seconds=self._wait)
        for message in messages:
            await self._handle(message)
        return len(messages)

    async def _handle(self, message: QueueMessage) -> None:
        token = request_id_var.set(f"job-{message.job_id}")
        try:
            job = await self._process(message.job_id)
        except Exception:
            logger.exception(
                "ingestion job crashed; leaving it for redelivery",
                extra={"job_id": message.job_id, "delivery_count": message.delivery_count},
            )
            return
        else:
            if job is not None and job.status is JobStatus.QUEUED:
                delay = retry_delay(
                    job.attempts,
                    base_seconds=self._retry_base,
                    max_seconds=self._retry_max,
                    jitter=self._jitter(),
                )
                await self._queue.enqueue(job.id, delay_seconds=delay)
                logger.info(
                    "ingestion job requeued",
                    extra={"job_id": job.id, "attempts": job.attempts, "delay_seconds": delay},
                )
            await self._queue.ack(message)
        finally:
            request_id_var.reset(token)
