# ADR-0006: Document parsing and chunking

- Status: Accepted
- Date: 2026-10-29

## Context

ING-01 and ING-02 need deterministic text extraction from PDF, DOCX, HTML and Markdown, and chunks with stable IDs and citable source locations. The corpus is bilingual (ADR-0005). A spike on a generated Vietnamese PDF showed that pypdf preserves diacritics but emits doubled spaces and breaks lines mid-sentence; after whitespace normalization and NFC the text matched the source exactly.

## Options considered

- **PDF:** pypdf (pure Python, BSD; text per page) vs pdfplumber (MIT; better tables, slower) vs PyMuPDF (fast, but AGPL). OCR for scanned PDFs is out of scope (the plan defers advanced OCR).
- **DOCX:** python-docx (MIT; paragraphs with styles, tables).
- **HTML:** BeautifulSoup with lxml vs selectolax. BeautifulSoup is ubiquitous and lxml is already pulled in by python-docx.
- **Chunking:** fixed-size character windows vs structure-aware packing vs semantic (embedding-based) splitting. Semantic splitting makes chunk boundaries depend on a model, which breaks determinism and couples ingestion to the embedder.

## Decision

**Libraries:** pypdf, python-docx, BeautifulSoup (lxml backend). They are pure parsing libraries with no network access, so they live in `ingestion/parsing/` rather than behind a port. A parser is a function from bytes to blocks, so swapping one later (for example pdfplumber for tables) touches one module.

**Format detection by content, not by client claims:** `%PDF-` magic, a ZIP containing `word/document.xml`, HTML markers, and UTF-8 text for `.md` and `.txt`. A mismatch between the declared type and the content is an `UnsupportedFormatError`.

**Parsed representation:** an ordered list of blocks, each with kind (heading, paragraph, list item, table), text, page (PDF) and enclosing section heading.
- PDF headings are detected with patterns common in the corpus (`Chương`, `Điều N.`, `Mục`, `Section`, numbered `1.` and `1.1`). Other lines on a page are joined into paragraphs.
- DOCX uses heading styles; tables become rows joined with ` | `.
- HTML drops `script`, `style`, `nav`, `header`, `footer`, `form` and hidden elements, and uses `h1`–`h4` as headings.

**Normalization** (every format, before anything else): Unicode NFC; common ligatures mapped (`ﬁ` to `fi`); zero-width and control characters removed; whitespace collapsed inside a block; blocks separated by one blank line. Normalization is idempotent.

**Chunking:** structure-aware packing over the normalized text.
- Units are sentences within blocks (split on `.`, `!`, `?`, `…` followed by whitespace), falling back to word windows for a single oversized sentence.
- Units are packed until `max_chars` (default 1200). A heading always starts a new chunk, so chunks do not straddle sections.
- Overlap: the next chunk repeats trailing units of the previous one up to `overlap_chars` (default 150), never crossing a section boundary.
- Every chunk's text is an exact slice `normalized_text[char_start:char_end]`, so citations can be highlighted precisely. `page` is the page of the chunk's first unit; `section` is the enclosing heading.
- Language per chunk: `vi` when at least 25% of words contain a Vietnamese tone mark or letter (`ă â đ ê ô ơ ư`), otherwise `en`; `und` when there are no words. Counting words rather than letters keeps English text with Vietnamese place names (`Đà Nẵng`) classified as English. The document language is `mixed` when each language holds at least 20% of the chunked text.
- Character budgets are a proxy for tokens: 1200 characters is far below the embedding model's 2048-token input for both languages.

**Limits and errors:** a maximum file size and page count, with typed, non-retryable errors: `unsupported_format`, `corrupt_document`, `encrypted_document`, `empty_document`, `document_too_large`.

**Checksum:** SHA-256 of the raw bytes, used for duplicate detection (ING-03).

## Consequences

- Same bytes and same settings always produce the same chunks, offsets and IDs. Changing `max_chars` or `overlap_chars` changes chunks, so both are recorded with each indexing run and benchmark result.
- Tables in PDFs are extracted as plain lines; a table-aware parser is a Week 4 experiment if the benchmark shows table questions failing.
- Scanned PDFs yield `empty_document`. OCR stays out of scope.
- Chunks after the first in a section do not contain the section heading. At indexing time (Week 3), the embedding input is `title › section › chunk text` (a contextual header), while the stored chunk text remains the exact slice used for citations. Week 4 measures the effect.
- Revisit chunk sizes in Week 4 using Recall@k and MRR, not intuition.
