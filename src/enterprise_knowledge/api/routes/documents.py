"""/v1 document upload, inspection and search (vertical slice v0.1)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from pydantic import BaseModel, Field, ValidationError

from enterprise_knowledge.api.errors import ForbiddenError
from enterprise_knowledge.api.identity import current_principal
from enterprise_knowledge.api.services import Services, get_services
from enterprise_knowledge.domain.access import AccessPolicy, Principal
from enterprise_knowledge.domain.documents import Document, DocumentChunk, DocumentStatus
from enterprise_knowledge.domain.errors import DocumentNotFoundError
from enterprise_knowledge.domain.ids import DocumentId
from enterprise_knowledge.domain.retrieval import RetrievedEvidence
from enterprise_knowledge.ingestion.errors import DocumentTooLargeError

router = APIRouter(prefix="/v1", tags=["documents"])

PrincipalDep = Annotated[Principal, Depends(current_principal)]
ServicesDep = Annotated[Services, Depends(get_services)]
_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"description": "Error body: {error: {category, message, request_id}}"}
    for code in (401, 403, 404, 409, 413, 415, 422, 502, 503)
}


class DocumentOut(BaseModel):
    id: str
    version: int
    title: str
    status: str
    language: str
    content_type: str
    allowed_groups: list[str]
    error_category: str | None

    @classmethod
    def of(cls, document: Document) -> "DocumentOut":
        return cls(
            id=document.id,
            version=document.version,
            title=document.title,
            status=document.status.value,
            language=document.language.value,
            content_type=document.content_type.value,
            allowed_groups=sorted(document.access.allowed_groups),
            error_category=document.error_category,
        )


class UploadOut(BaseModel):
    document: DocumentOut
    chunk_count: int
    duplicate: bool


class ChunkOut(BaseModel):
    id: str
    index: int
    text: str
    page: int | None
    section: str | None
    char_start: int | None
    char_end: int | None
    language: str

    @classmethod
    def of(cls, chunk: DocumentChunk) -> "ChunkOut":
        return cls(
            id=chunk.id,
            index=chunk.chunk_index,
            text=chunk.text,
            page=chunk.source.page,
            section=chunk.source.section,
            char_start=chunk.source.char_start,
            char_end=chunk.source.char_end,
            language=chunk.language.value,
        )


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=5, ge=1, le=20)


class EvidenceOut(BaseModel):
    chunk_id: str
    document_id: str
    document_version: int
    title: str
    text: str
    score: float
    page: int | None
    section: str | None
    language: str

    @classmethod
    def of(cls, hit: RetrievedEvidence) -> "EvidenceOut":
        return cls(
            chunk_id=hit.chunk_id,
            document_id=hit.document_id,
            document_version=hit.document_version,
            title=hit.title,
            text=hit.text,
            score=round(hit.score, 6),
            page=hit.source.page,
            section=hit.source.section,
            language=hit.language.value,
        )


class SearchOut(BaseModel):
    results: list[EvidenceOut]


@router.post(
    "/documents",
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": UploadOut, "description": "Identical document already indexed"},
        **_ERRORS,
    },
)
async def upload_document(
    principal: PrincipalDep,
    services: ServicesDep,
    response: Response,
    file: Annotated[UploadFile, File(description="PDF, DOCX, HTML, Markdown or text")],
    allowed_groups: Annotated[str, Form(description="Comma-separated groups that may read it")],
    title: Annotated[str | None, Form()] = None,
    document_id: Annotated[str | None, Form(description="Upload a new version of this")] = None,
) -> UploadOut:
    access = _access_policy(principal, allowed_groups)
    if document_id is not None:
        await _readable_document(services, principal, DocumentId(document_id))

    data = await file.read(services.max_upload_bytes + 1)
    if len(data) > services.max_upload_bytes:
        raise DocumentTooLargeError(f"upload exceeds {services.max_upload_bytes} bytes")

    result = await services.ingest(
        data=data,
        filename=file.filename or "upload",
        access=access,
        document_id=DocumentId(document_id) if document_id else None,
        title=title,
    )
    if result.duplicate:
        response.status_code = status.HTTP_200_OK
    return UploadOut(
        document=DocumentOut.of(result.document),
        chunk_count=result.chunk_count,
        duplicate=result.duplicate,
    )


@router.get("/documents/{document_id}", responses=_ERRORS)
async def get_document(
    document_id: str, principal: PrincipalDep, services: ServicesDep
) -> DocumentOut:
    return DocumentOut.of(await _readable_document(services, principal, DocumentId(document_id)))


@router.get("/documents/{document_id}/chunks", responses=_ERRORS)
async def list_chunks(
    document_id: str,
    principal: PrincipalDep,
    services: ServicesDep,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> list[ChunkOut]:
    document = await _readable_document(services, principal, DocumentId(document_id))
    chunks = await services.documents.list_chunks(
        principal.tenant_id, document.id, version or document.version
    )
    return [ChunkOut.of(c) for c in chunks if principal.can_access(c.access)]


@router.delete(
    "/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_ERRORS
)
async def delete_document(document_id: str, principal: PrincipalDep, services: ServicesDep) -> None:
    """Remove every version from search and storage. Deleting again also returns 204."""
    await services.delete(principal=principal, document_id=DocumentId(document_id))


@router.post("/search", responses=_ERRORS)
async def search(body: SearchIn, principal: PrincipalDep, services: ServicesDep) -> SearchOut:
    hits = await services.search(principal, body.query, k=body.k)
    return SearchOut(results=[EvidenceOut.of(h) for h in hits])


def _access_policy(principal: Principal, allowed_groups: str) -> AccessPolicy:
    groups = {g.strip() for g in allowed_groups.split(",") if g.strip()}
    # Uploaders may only share with groups they belong to, so nobody can plant content
    # into another group's view.
    outside = groups - principal.groups
    if outside:
        raise ForbiddenError(f"not a member of: {', '.join(sorted(outside))}")
    try:
        return AccessPolicy.model_validate(
            {"tenant_id": principal.tenant_id, "allowed_groups": frozenset(groups)}
        )
    except ValidationError as exc:
        raise ForbiddenError("allowed_groups must name at least one valid group") from exc


async def _readable_document(
    services: Services, principal: Principal, document_id: DocumentId
) -> Document:
    """The current version, or 404 when absent, deleted or not readable by the caller.
    Unreadable and missing look the same, so callers cannot probe for documents."""
    document = await services.documents.get_document(principal.tenant_id, document_id)
    if (
        document is None
        or document.status is DocumentStatus.DELETED
        or not principal.can_access(document.access)
    ):
        raise DocumentNotFoundError(f"document {document_id} not found")
    return document
