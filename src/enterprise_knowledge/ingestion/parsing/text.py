"""Markdown and plain text: paragraphs separated by blank lines; Markdown headings and lists."""

import re

from enterprise_knowledge.ingestion.parsing.model import BlockBuilder, BlockKind, ParsedDocument

_MD_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*$")
_MD_LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.*)$")


def parse_text(text: str, *, markdown: bool) -> ParsedDocument:
    builder = BlockBuilder()
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            builder.add(BlockKind.PARAGRAPH, " ".join(paragraph))
            paragraph.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if markdown and (heading := _MD_HEADING.match(line)):
            flush()
            builder.add(BlockKind.HEADING, heading.group(1))
        elif markdown and (item := _MD_LIST_ITEM.match(line)):
            flush()
            builder.add(BlockKind.LIST_ITEM, item.group(1))
        else:
            paragraph.append(line)
    flush()
    return builder.build(title=None)
