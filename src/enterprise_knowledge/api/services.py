"""Use cases and repositories the routes depend on, provided by the composition root."""

from dataclasses import dataclass

from fastapi import Request

from enterprise_knowledge.api.errors import ServiceUnavailableError
from enterprise_knowledge.domain.ports import DocumentRepository
from enterprise_knowledge.ingestion.delete import DeleteDocument
from enterprise_knowledge.ingestion.ingest import IngestDocument
from enterprise_knowledge.retrieval.search import SearchKnowledge


@dataclass(frozen=True, slots=True)
class Services:
    documents: DocumentRepository
    ingest: IngestDocument
    delete: DeleteDocument
    search: SearchKnowledge
    max_upload_bytes: int


def get_services(request: Request) -> Services:
    services: Services | None = getattr(request.app.state, "services", None)
    if services is None:
        raise ServiceUnavailableError("service is starting or not configured")
    return services
