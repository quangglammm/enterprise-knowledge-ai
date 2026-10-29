---
paths:
  - "tests/**/*.py"
---

# Testing conventions

## Layout

- `tests/unit/`: no network, no database, no filesystem outside `tmp_path`. Must run in under a few seconds total.
- `tests/integration/`: real Postgres from docker compose. Mark every test `@pytest.mark.integration`.
- `tests/evaluation/`: benchmark and quality checks. Never part of the default run.
- Mirror the source path: `src/enterprise_knowledge/ingestion/chunking.py` → `tests/unit/ingestion/test_chunking.py`.
- Fixture documents live in `datasets/fixtures/`, small and committed. Generate corrupt or empty cases in the test where possible.

## Writing tests

- Name tests by behavior: `test_duplicate_upload_does_not_create_new_chunks`, not `test_ingest_2`.
- Arrange, act, assert, separated by blank lines. One behavior per test.
- Use `pytest.mark.parametrize` for input variations instead of loops or copy-paste.
- Assert on outcomes (returned values, stored state, raised error type and category), not on internal calls.
- `pytest.raises(SomeError, match=...)` must name the specific error type.
- Async tests are plain `async def` (asyncio mode is auto).

## Fakes over mocks

- For ports (`ModelProvider`, `Embedder`, `VectorRepository`, `JobQueue`, `DocumentStore`), write small in-memory fakes in `tests/fakes/` that implement the Protocol. Reuse them everywhere.
- Fake embedders must be deterministic and produce vectors with the same dimension as production.
- Fake model providers return scripted responses and can simulate throttling, timeouts and invalid JSON.
- Use `unittest.mock` only for things that have no port, such as time or randomness. Patch where the object is looked up.

## Required negative tests

When a feature touches these, the test for the failure case is part of the same change:

- Empty, corrupt or unsupported input produces a typed error, and the worker or API stays healthy.
- Duplicate processing is idempotent.
- A user without access never receives restricted chunks, even when they are the best match.
- Retrieved text containing instructions does not change behavior.
- Retries are bounded; a permanently failing dependency ends in a recorded failure.
