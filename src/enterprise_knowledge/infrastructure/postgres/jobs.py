"""PostgreSQL JobRepository and JobQueue (JOB-01, ADR-0016).

The queue is a table leased with ``FOR UPDATE SKIP LOCKED``: concurrent workers never take
the same message, and a message whose lease (the visibility timeout) runs out is delivered
again, as with SQS. Times come from the database clock, so workers on different hosts agree.
"""

import asyncio
import time
from typing import Any, Self

from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from enterprise_knowledge.domain.errors import JobAlreadyExistsError, JobNotFoundError
from enterprise_knowledge.domain.ids import DocumentId, JobId, TenantId
from enterprise_knowledge.domain.jobs import IngestionJob, JobStatus
from enterprise_knowledge.domain.ports import QueueMessage

_POLL_SECONDS = 0.5
_FIELDS = (
    "id",
    "tenant_id",
    "document_id",
    "document_version",
    "status",
    "attempts",
    "max_attempts",
    "error_category",
    "use_parsed_title",
    "created_at",
    "updated_at",
)
_COLUMNS = ", ".join(_FIELDS)
_VALUES = ", ".join(f"%({f})s" for f in _FIELDS)
_UPDATES = ", ".join(f"{f} = %({f})s" for f in _FIELDS if f != "id")

_RECEIVE_SQL = """
UPDATE job_queue q
SET deliveries = q.deliveries + 1,
    receipt = gen_random_uuid()::text,
    available_at = now() + make_interval(secs => %(visibility)s)
FROM (
    SELECT id FROM job_queue
    WHERE available_at <= now()
    ORDER BY available_at, id
    LIMIT %(limit)s
    FOR UPDATE SKIP LOCKED
) ready
WHERE q.id = ready.id
RETURNING q.job_id, q.receipt, q.deliveries
"""


class PostgresJobStore:
    def __init__(self, pool: AsyncConnectionPool, *, visibility_seconds: float) -> None:
        self._pool = pool
        self._visibility = visibility_seconds

    @classmethod
    async def connect(
        cls,
        conninfo: str,
        *,
        visibility_seconds: float,
        min_size: int = 1,
        max_size: int = 5,
        connect_timeout: float = 10.0,
    ) -> Self:
        pool = AsyncConnectionPool(
            conninfo, min_size=min_size, max_size=max_size, timeout=connect_timeout, open=False
        )
        await pool.open(wait=True, timeout=connect_timeout)
        return cls(pool, visibility_seconds=visibility_seconds)

    async def close(self) -> None:
        await self._pool.close()

    # --- JobRepository ------------------------------------------------------------------

    async def add_job(self, job: IngestionJob) -> None:
        try:
            async with self._pool.connection() as conn:
                await conn.execute(
                    f"INSERT INTO ingestion_jobs ({_COLUMNS}) VALUES ({_VALUES})",  # noqa: S608
                    _params(job),
                )
        except UniqueViolation as exc:
            raise JobAlreadyExistsError(f"job {job.id} exists") from exc

    async def get_job(self, job_id: JobId) -> IngestionJob | None:
        return await self._one(
            f"SELECT {_COLUMNS} FROM ingestion_jobs WHERE id = %s",  # noqa: S608
            (job_id,),
        )

    async def update_job(self, job: IngestionJob) -> None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE ingestion_jobs SET {_UPDATES} WHERE id = %(id)s",  # noqa: S608
                _params(job),
            )
            if cur.rowcount == 0:
                raise JobNotFoundError(f"job {job.id} not found")

    async def latest_job_for(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> IngestionJob | None:
        return await self._one(
            f"SELECT {_COLUMNS} FROM ingestion_jobs"  # noqa: S608
            " WHERE tenant_id = %s AND document_id = %s AND document_version = %s"
            " ORDER BY created_at DESC, id DESC LIMIT 1",
            (tenant_id, document_id, version),
        )

    async def _one(self, query: str, params: tuple[Any, ...]) -> IngestionJob | None:
        async with self._pool.connection() as conn:
            cur = await conn.cursor(row_factory=dict_row).execute(query, params)
            row = await cur.fetchone()
        return None if row is None else _job(row)

    # --- JobQueue -----------------------------------------------------------------------

    async def enqueue(self, job_id: JobId, *, delay_seconds: float = 0.0) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO job_queue (job_id, available_at)"
                " VALUES (%s, now() + make_interval(secs => %s))",
                (job_id, delay_seconds),
            )

    async def receive(self, *, max_messages: int, wait_seconds: float) -> list[QueueMessage]:
        deadline = time.monotonic() + wait_seconds
        while True:
            async with self._pool.connection() as conn:
                cur = await conn.cursor(row_factory=dict_row).execute(
                    _RECEIVE_SQL, {"visibility": self._visibility, "limit": max_messages}
                )
                rows = await cur.fetchall()
            remaining = deadline - time.monotonic()
            if rows or remaining <= 0:
                return [
                    QueueMessage(
                        job_id=JobId(r["job_id"]),
                        receipt=r["receipt"],
                        delivery_count=r["deliveries"],
                    )
                    for r in rows
                ]
            await asyncio.sleep(min(_POLL_SECONDS, remaining))

    async def ack(self, message: QueueMessage) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("DELETE FROM job_queue WHERE receipt = %s", (message.receipt,))


def _params(job: IngestionJob) -> dict[str, Any]:
    return job.model_dump() | {"status": job.status.value}


def _job(row: dict[str, Any]) -> IngestionJob:
    return IngestionJob.model_validate(row | {"status": JobStatus(row["status"])})
