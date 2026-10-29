"""Format-independent parse result: ordered blocks with page and section context."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from enterprise_knowledge.ingestion.errors import EmptyDocumentError
from enterprise_knowledge.ingestion.normalize import normalize_text


class BlockKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"


class Block(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: BlockKind
    text: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    section: str | None = None


class ParsedDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str | None
    blocks: tuple[Block, ...] = Field(min_length=1)
    page_count: int | None = None


class BlockBuilder:
    """Collects normalized, non-empty blocks and tracks the enclosing heading."""

    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self._section: str | None = None

    def add(self, kind: BlockKind, raw_text: str, *, page: int | None = None) -> None:
        text = normalize_text(raw_text)
        if not text:
            return
        if kind is BlockKind.HEADING:
            self._section = text
        self.blocks.append(Block(kind=kind, text=text, page=page, section=self._section))

    def build(self, *, title: str | None, page_count: int | None = None) -> ParsedDocument:
        """Finish parsing. A document with no extractable text is an error, not an empty result."""
        if not self.blocks:
            raise EmptyDocumentError("no extractable text (scanned or blank document?)")
        heading = next((b.text for b in self.blocks if b.kind is BlockKind.HEADING), None)
        return ParsedDocument(
            title=title or heading, blocks=tuple(self.blocks), page_count=page_count
        )
