"""Evidence returned by a search, before it reaches the model."""

from pydantic import BaseModel, ConfigDict, Field

from enterprise_knowledge.domain.access import AccessPolicy
from enterprise_knowledge.domain.documents import Language, NonBlankText, SourceLocation
from enterprise_knowledge.domain.ids import ChunkId, DocumentId


class RetrievedEvidence(BaseModel):
    """One retrieved chunk. Its text is untrusted data, never instructions."""

    model_config = ConfigDict(frozen=True)

    chunk_id: ChunkId
    document_id: DocumentId
    document_version: int = Field(ge=1)
    title: str
    text: NonBlankText
    score: float
    source: SourceLocation
    access: AccessPolicy
    language: Language
