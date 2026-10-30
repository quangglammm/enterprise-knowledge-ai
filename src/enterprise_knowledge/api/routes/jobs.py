"""/v1 ingestion job status (JOB-01)."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from enterprise_knowledge.api.identity import current_principal
from enterprise_knowledge.api.services import Services, get_services
from enterprise_knowledge.domain.access import Principal
from enterprise_knowledge.domain.errors import JobNotFoundError
from enterprise_knowledge.domain.ids import JobId
from enterprise_knowledge.domain.jobs import IngestionJob

router = APIRouter(prefix="/v1", tags=["jobs"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"description": "Error body: {error: {category, message, request_id}}"}
    for code in (401, 404, 503)
}


class JobOut(BaseModel):
    id: str
    status: str
    attempts: int
    max_attempts: int
    error_category: str | None
    document_id: str
    document_version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, job: IngestionJob) -> "JobOut":
        return cls(
            id=job.id,
            status=job.status.value,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            error_category=job.error_category,
            document_id=job.document_id,
            document_version=job.document_version,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


@router.get("/jobs/{job_id}", responses=_ERRORS)
async def get_job(
    job_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    services: Annotated[Services, Depends(get_services)],
) -> JobOut:
    """A job is visible to whoever may read its document version; otherwise 404, so job
    IDs cannot be used to probe for documents in other tenants or groups."""
    job = await services.jobs.get_job(JobId(job_id))
    if job is None or job.tenant_id != principal.tenant_id:
        raise JobNotFoundError(f"job {job_id} not found")
    document = await services.documents.get_document_version(
        job.tenant_id, job.document_id, job.document_version
    )
    if document is None or not principal.can_access(document.access):
        raise JobNotFoundError(f"job {job_id} not found")
    return JobOut.of(job)
