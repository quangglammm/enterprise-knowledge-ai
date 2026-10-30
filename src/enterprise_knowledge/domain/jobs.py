"""Ingestion job state machine (JOB-01).

    QUEUED --start--> RUNNING --succeed--> SUCCEEDED
      |                  |
      |                  +--fail(retryable, attempts left)--> QUEUED
      |                  +--fail(otherwise)-----------------> FAILED
      +--abandon (never delivered, e.g. enqueue failed)-----> FAILED

Transitions return new instances; invalid transitions raise.
"""

from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from enterprise_knowledge.domain.errors import InvalidJobTransitionError
from enterprise_knowledge.domain.ids import DocumentId, JobId, TenantId


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


_TERMINAL = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED})


class IngestionJob(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: JobId
    tenant_id: TenantId
    document_id: DocumentId
    document_version: int = Field(ge=1)
    status: JobStatus
    attempts: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    error_category: str | None = None
    # False when the uploader gave a title, so the worker keeps it instead of the parsed one.
    use_parsed_title: bool = True

    @classmethod
    def new(
        cls,
        *,
        job_id: JobId,
        tenant_id: TenantId,
        document_id: DocumentId,
        document_version: int,
        max_attempts: int,
        now: AwareDatetime,
        use_parsed_title: bool = True,
    ) -> "IngestionJob":
        return cls(
            id=job_id,
            tenant_id=tenant_id,
            document_id=document_id,
            document_version=document_version,
            status=JobStatus.QUEUED,
            attempts=0,
            max_attempts=max_attempts,
            created_at=now,
            updated_at=now,
            use_parsed_title=use_parsed_title,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL

    def start(self, *, now: AwareDatetime) -> "IngestionJob":
        self._require(JobStatus.QUEUED, "start")
        return self._evolve(status=JobStatus.RUNNING, attempts=self.attempts + 1, updated_at=now)

    def succeed(self, *, now: AwareDatetime) -> "IngestionJob":
        self._require(JobStatus.RUNNING, "succeed")
        return self._evolve(status=JobStatus.SUCCEEDED, updated_at=now, error_category=None)

    def fail(self, *, now: AwareDatetime, error_category: str, retryable: bool) -> "IngestionJob":
        self._require(JobStatus.RUNNING, "fail")
        retry = retryable and self.attempts < self.max_attempts
        return self._evolve(
            status=JobStatus.QUEUED if retry else JobStatus.FAILED,
            updated_at=now,
            error_category=error_category,
        )

    def abandon(self, *, now: AwareDatetime, error_category: str) -> "IngestionJob":
        self._require(JobStatus.QUEUED, "abandon")
        return self._evolve(status=JobStatus.FAILED, updated_at=now, error_category=error_category)

    def _require(self, expected: JobStatus, action: str) -> None:
        if self.status is not expected:
            raise InvalidJobTransitionError(
                f"cannot {action} job {self.id} in status {self.status.value}"
            )

    def _evolve(self, **changes: object) -> "IngestionJob":
        return self.model_validate(self.model_dump() | changes)
