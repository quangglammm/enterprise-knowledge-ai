"""In-memory JobRepository with the same semantics as the Postgres adapter."""

from enterprise_knowledge.domain.errors import JobAlreadyExistsError, JobNotFoundError
from enterprise_knowledge.domain.ids import DocumentId, JobId, TenantId
from enterprise_knowledge.domain.jobs import IngestionJob


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[JobId, IngestionJob] = {}

    async def add_job(self, job: IngestionJob) -> None:
        if job.id in self._jobs:
            raise JobAlreadyExistsError(f"job {job.id} exists")
        self._jobs[job.id] = job

    async def get_job(self, job_id: JobId) -> IngestionJob | None:
        return self._jobs.get(job_id)

    async def update_job(self, job: IngestionJob) -> None:
        if job.id not in self._jobs:
            raise JobNotFoundError(f"job {job.id} not found")
        self._jobs[job.id] = job

    async def latest_job_for(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> IngestionJob | None:
        jobs = [
            j
            for j in self._jobs.values()
            if (j.tenant_id, j.document_id, j.document_version) == (tenant_id, document_id, version)
        ]
        return max(jobs, key=lambda j: (j.created_at, j.id), default=None)
