-- 0001: documents, chunks and vector search (ADR-0003, ADR-0007).
-- Applied files are never edited; schema changes go in a new numbered file.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    tenant_id      text        NOT NULL,
    id             text        NOT NULL,
    version        integer     NOT NULL CHECK (version >= 1),
    title          text        NOT NULL,
    filename       text        NOT NULL,
    content_type   text        NOT NULL,
    checksum       char(64)    NOT NULL,
    status         text        NOT NULL
                   CHECK (status IN ('pending', 'indexed', 'failed', 'deleted')),
    allowed_groups text[]      NOT NULL CHECK (cardinality(allowed_groups) > 0),
    language       text        NOT NULL,
    error_category text,
    created_at     timestamptz NOT NULL,
    updated_at     timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, id, version),
    CHECK (status <> 'failed' OR error_category IS NOT NULL)
);

-- Duplicate detection (ING-03) looks up live documents by content hash.
CREATE INDEX documents_checksum_idx ON documents (tenant_id, checksum)
    WHERE status <> 'deleted';

CREATE TABLE chunks (
    id               text         PRIMARY KEY,
    tenant_id        text         NOT NULL,
    document_id      text         NOT NULL,
    document_version integer      NOT NULL,
    chunk_index      integer      NOT NULL CHECK (chunk_index >= 0),
    text             text         NOT NULL,
    page             integer,
    section          text,
    char_start       integer,
    char_end         integer,
    -- Denormalized from the document version so the ACL filter is part of the vector query.
    allowed_groups   text[]       NOT NULL CHECK (cardinality(allowed_groups) > 0),
    language         text         NOT NULL,
    embedding_model  text         NOT NULL,
    -- Dimension fixed by ADR-0004; changing the embedding model needs a migration and re-index.
    embedding        vector(1024) NOT NULL,
    -- True only for chunks of the document's highest indexed version (ADR-0007).
    searchable       boolean      NOT NULL DEFAULT false,
    FOREIGN KEY (tenant_id, document_id, document_version)
        REFERENCES documents (tenant_id, id, version) ON DELETE CASCADE,
    UNIQUE (tenant_id, document_id, document_version, chunk_index)
);

CREATE INDEX chunks_tenant_searchable_idx ON chunks (tenant_id, searchable);
CREATE INDEX chunks_allowed_groups_idx ON chunks USING gin (allowed_groups);
CREATE INDEX chunks_embedding_hnsw_idx ON chunks USING hnsw (embedding vector_cosine_ops);
