"""Use cases and repositories the routes depend on, provided by the composition root."""

from dataclasses import dataclass

from fastapi import Request

from enterprise_knowledge.agents.modes import AnswerMode, AnswerModes
from enterprise_knowledge.api.errors import ServiceUnavailableError
from enterprise_knowledge.domain.ports import DocumentRepository, JobRepository
from enterprise_knowledge.ingestion.delete import DeleteDocument
from enterprise_knowledge.ingestion.jobs import SubmitDocument
from enterprise_knowledge.retrieval.search import SearchKnowledge


@dataclass(frozen=True, slots=True)
class Services:
    documents: DocumentRepository
    # Uploads become ingestion jobs; the worker (eka-worker) processes them (JOB-01).
    submit: SubmitDocument
    jobs: JobRepository
    delete: DeleteDocument
    search: SearchKnowledge
    max_upload_bytes: int
    # None until a chat model adapter is configured; /v1/answers then returns 503.
    answer: AnswerModes | None = None
    default_answer_mode: AnswerMode = "direct"


def get_services(request: Request) -> Services:
    services: Services | None = getattr(request.app.state, "services", None)
    if services is None:
        raise ServiceUnavailableError("service is starting or not configured")
    return services
