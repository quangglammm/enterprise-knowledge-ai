"""DOCX extraction with python-docx: heading styles, list styles and tables, in body order."""

import io
import zipfile

from docx import Document as open_docx
from docx.opc.exceptions import PackageNotFoundError
from docx.table import Table
from docx.text.paragraph import Paragraph

from enterprise_knowledge.ingestion.errors import CorruptDocumentError
from enterprise_knowledge.ingestion.normalize import normalize_text
from enterprise_knowledge.ingestion.parsing.model import BlockBuilder, BlockKind, ParsedDocument

_HEADING_STYLES = ("Heading", "Title")


def parse_docx(data: bytes) -> ParsedDocument:
    builder = BlockBuilder()
    try:
        document = open_docx(io.BytesIO(data))
        for item in document.iter_inner_content():
            if isinstance(item, Paragraph):
                builder.add(_paragraph_kind(item), item.text)
            elif isinstance(item, Table):
                _add_table(builder, item)
        core_title = document.core_properties.title
    except (PackageNotFoundError, zipfile.BadZipFile) as exc:
        raise CorruptDocumentError("DOCX package could not be opened") from exc
    except Exception as exc:
        # python-docx surfaces malformed parts as arbitrary errors (AttributeError, KeyError,
        # lxml errors). At this third-party boundary every one of them means "corrupt".
        raise CorruptDocumentError("DOCX content could not be read") from exc

    return builder.build(title=normalize_text(core_title) if core_title else None)


def _paragraph_kind(paragraph: Paragraph) -> BlockKind:
    style = paragraph.style.name if paragraph.style is not None and paragraph.style.name else ""
    if style.startswith(_HEADING_STYLES):
        return BlockKind.HEADING
    if "List" in style:
        return BlockKind.LIST_ITEM
    return BlockKind.PARAGRAPH


def _add_table(builder: BlockBuilder, table: Table) -> None:
    for row in table.rows:
        # Merged cells repeat the same cell object across columns; keep each once.
        seen: list[str] = []
        for cell in row.cells:
            text = normalize_text(cell.text)
            if text and (not seen or seen[-1] != text):
                seen.append(text)
        builder.add(BlockKind.TABLE, " | ".join(seen))
