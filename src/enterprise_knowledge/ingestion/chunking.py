"""Structure-aware, deterministic chunking (ING-02, ADR-0006).

The parsed blocks are joined into one normalized text (blocks separated by a blank line).
Blocks are split into sentence units, and units are packed into chunks that:

- never exceed ``max_chars``,
- start at every heading, so a chunk never spans two sections,
- never consist of headings alone: consecutive headings merge into the following chunk, and a
  heading whose body cannot fit beside it is dropped from the text (it remains the chunk's
  ``section`` and part of the embedding header),
- repeat up to ``overlap_chars`` of trailing units from the previous chunk of the same section,
- are exact slices of the normalized text, so ``char_start``/``char_end`` locate citations.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from enterprise_knowledge.domain.documents import (
    Document,
    DocumentChunk,
    Language,
    SourceLocation,
)
from enterprise_knowledge.ingestion.language import detect_language
from enterprise_knowledge.ingestion.parsing import BlockKind, ParsedDocument

BLOCK_SEPARATOR = "\n\n"
_SENTENCE_BREAK = re.compile(r"(?<=[.!?…])\s+")


class ChunkingSettings(BaseModel):
    """Recorded with every indexing run: changing them changes chunks and benchmark results."""

    model_config = ConfigDict(frozen=True)

    max_chars: int = Field(default=1200, ge=100)
    overlap_chars: int = Field(default=150, ge=0)
    # Opt-in (ADR-0006 amendment): a heading starts a new chunk only when its whole section
    # does not fit beside the current one, so short sections share a chunk.
    pack_sections: bool = False

    @model_validator(mode="after")
    def _overlap_leaves_room(self) -> Self:
        if self.overlap_chars * 2 >= self.max_chars:
            raise ValueError("overlap_chars must be less than half of max_chars")
        return self


class ChunkDraft(BaseModel):
    """A chunk before it is bound to a stored document version."""

    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0)
    text: str = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=1)
    page: int | None
    section: str | None
    language: Language


@dataclass(frozen=True, slots=True)
class _Unit:
    start: int
    end: int
    page: int | None
    section: str | None
    starts_section: bool
    heading: bool


def chunk_document(
    parsed: ParsedDocument, settings: ChunkingSettings | None = None
) -> tuple[str, list[ChunkDraft]]:
    """Return the normalized document text and its chunks."""
    settings = settings or ChunkingSettings()
    text, units = _units(parsed, settings.max_chars)
    groups = _pack(units, settings)
    drafts = []
    for index, group in enumerate(groups):
        start, end = group[0].start, group[-1].end
        chunk_text = text[start:end]
        drafts.append(
            ChunkDraft(
                index=index,
                text=chunk_text,
                char_start=start,
                char_end=end,
                page=group[0].page,
                section=next((u.section for u in group if not u.heading), group[-1].section),
                language=detect_language(chunk_text),
            )
        )
    return text, drafts


def build_chunks(document: Document, drafts: Sequence[ChunkDraft]) -> list[DocumentChunk]:
    """Bind drafts to a document version: derives chunk IDs and copies the access policy."""
    if [d.index for d in drafts] != list(range(len(drafts))):
        raise ValueError("chunk drafts must have contiguous index values starting at 0")
    return [
        DocumentChunk.for_document(
            document,
            index=draft.index,
            text=draft.text,
            source=SourceLocation(
                page=draft.page,
                section=draft.section,
                char_start=draft.char_start,
                char_end=draft.char_end,
            ),
            language=draft.language,
        )
        for draft in drafts
    ]


def _units(parsed: ParsedDocument, max_chars: int) -> tuple[str, list[_Unit]]:
    parts: list[str] = []
    units: list[_Unit] = []
    offset = 0
    for block in parsed.blocks:
        if parts:
            parts.append(BLOCK_SEPARATOR)
            offset += len(BLOCK_SEPARATOR)
        heading = block.kind is BlockKind.HEADING
        for i, (start, end) in enumerate(_sentence_spans(block.text, max_chars)):
            units.append(
                _Unit(
                    start=offset + start,
                    end=offset + end,
                    page=block.page,
                    section=block.section,
                    starts_section=heading and i == 0,
                    heading=heading,
                )
            )
        parts.append(block.text)
        offset += len(block.text)
    return "".join(parts), units


def _sentence_spans(text: str, max_chars: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_BREAK.finditer(text):
        spans.extend(_fit(text, start, match.start(), max_chars))
        start = match.end()
    spans.extend(_fit(text, start, len(text), max_chars))
    return spans


def _fit(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    """Split [start, end) into pieces of at most max_chars, preferring word boundaries."""
    pieces: list[tuple[int, int]] = []
    while end - start > max_chars:
        cut = text.rfind(" ", start + 1, start + max_chars + 1)
        if cut == -1:
            pieces.append((start, start + max_chars))
            start += max_chars
        else:
            pieces.append((start, cut))
            start = cut + 1
    if end > start:
        pieces.append((start, end))
    return pieces


def _pack(units: list[_Unit], settings: ChunkingSettings) -> list[list[_Unit]]:
    run_ends = _section_run_ends(units) if settings.pack_sections else {}
    groups: list[list[_Unit]] = []
    current: list[_Unit] = []
    absorb_until = -1
    for i, unit in enumerate(units):
        if current:
            if unit.end <= absorb_until:
                current.append(unit)  # inside a section already known to fit
                continue
            run_end = run_ends.get(i)
            if (
                run_end is not None
                and not all(u.heading for u in current)
                and run_end - current[0].start <= settings.max_chars
            ):
                absorb_until = run_end
                current.append(unit)
                continue
            headings_only = all(u.heading for u in current)
            too_long = unit.end - current[0].start > settings.max_chars
            if unit.starts_section and headings_only and not too_long:
                current.append(unit)  # consecutive headings travel with the next body
                continue
            if unit.starts_section or too_long:
                if not headings_only:
                    groups.append(current)
                current = (
                    []
                    if unit.starts_section or headings_only
                    else _overlap(current, unit, settings)
                )
        current.append(unit)
    if current and (not all(u.heading for u in current) or not groups):
        groups.append(current)
    return groups


def _section_run_ends(units: list[_Unit]) -> dict[int, int]:
    """For each unit that opens a section run (headings plus their body), where the run ends."""
    starts = [
        i for i, u in enumerate(units) if u.starts_section and (i == 0 or not units[i - 1].heading)
    ]
    ends = [units[j - 1].end for j in starts[1:]] + [units[-1].end] if starts else []
    return dict(zip(starts, ends, strict=True))


def _overlap(previous: list[_Unit], unit: _Unit, settings: ChunkingSettings) -> list[_Unit]:
    """Trailing units of the previous chunk to repeat, never its first unit (ensures progress)."""
    seed: list[_Unit] = []
    for candidate in reversed(previous[1:]):
        if previous[-1].end - candidate.start > settings.overlap_chars:
            break
        if unit.end - candidate.start > settings.max_chars:
            break
        seed.insert(0, candidate)
    return seed
