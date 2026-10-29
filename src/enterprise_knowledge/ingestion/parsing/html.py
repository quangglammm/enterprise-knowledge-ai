"""HTML extraction with BeautifulSoup: main content only, without boilerplate or hidden parts."""

import re

from bs4 import BeautifulSoup, Tag

from enterprise_knowledge.ingestion.normalize import normalize_text
from enterprise_knowledge.ingestion.parsing.model import BlockBuilder, BlockKind, ParsedDocument

_BOILERPLATE = (
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "nav",
    "header",
    "footer",
    "form",
    "aside",
    "iframe",
)
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.IGNORECASE)
_KINDS: dict[str, BlockKind] = {
    "h1": BlockKind.HEADING,
    "h2": BlockKind.HEADING,
    "h3": BlockKind.HEADING,
    "h4": BlockKind.HEADING,
    "p": BlockKind.PARAGRAPH,
    "pre": BlockKind.PARAGRAPH,
    "blockquote": BlockKind.PARAGRAPH,
    "dt": BlockKind.PARAGRAPH,
    "dd": BlockKind.PARAGRAPH,
    "li": BlockKind.LIST_ITEM,
    "tr": BlockKind.TABLE,
}


def parse_html(text: str) -> ParsedDocument:
    soup = BeautifulSoup(text, "lxml")
    title_tag = soup.find("title")
    title = normalize_text(title_tag.get_text()) if isinstance(title_tag, Tag) else None

    for element in soup.find_all(_BOILERPLATE):
        element.decompose()
    for element in soup.find_all(_is_hidden):
        element.decompose()

    root = soup.body or soup
    builder = BlockBuilder()
    for element in root.find_all(list(_KINDS)):
        if _has_block_ancestor(element):
            continue  # the outermost block already contains this text
        kind = _KINDS[element.name]
        if kind is BlockKind.TABLE:
            cells = [c.get_text(" ") for c in element.find_all(["td", "th"])]
            builder.add(kind, " | ".join(normalize_text(c) for c in cells if normalize_text(c)))
        else:
            builder.add(kind, element.get_text(" "))
    return builder.build(title=title or None)


def _is_hidden(element: Tag) -> bool:
    if element.has_attr("hidden") or element.get("aria-hidden") == "true":
        return True
    style = element.get("style")
    return isinstance(style, str) and bool(_HIDDEN_STYLE.search(style))


def _has_block_ancestor(element: Tag) -> bool:
    return any(parent.name in _KINDS for parent in element.parents)
