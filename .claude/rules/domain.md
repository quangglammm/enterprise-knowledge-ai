---
paths:
  - "src/enterprise_knowledge/domain/**/*.py"
---

# Domain layer

- Pure Python plus Pydantic only. Importing FastAPI, Starlette, boto3, SQLAlchemy, psycopg, httpx, any LLM SDK, or another `enterprise_knowledge` package outside `domain` is not allowed here.
- Ports are `typing.Protocol` classes named for the capability (`Embedder`, `VectorRepository`), with async methods where the real implementation does I/O.
- IDs are typed (`NewType` or a small Pydantic model), not bare `str`, so a chunk ID cannot be passed where a document ID is expected.
- Every model that represents indexed content carries `tenant_id` and access-control fields. Do not add a chunk or evidence model without them.
- Chunk IDs are deterministic: derived from document ID, document version and chunk index, so reprocessing unchanged input produces the same IDs.
- Embedding records store `embedding_model` and `embedding_dim` alongside the vector.
- Timestamps are timezone-aware UTC.
