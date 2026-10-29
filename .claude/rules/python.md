---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
---

# Python conventions

## Types

- Code must pass `mypy --strict`. Annotate every function, including `-> None`.
- Use modern syntax: `list[str]`, `X | None`, `type` aliases. No `typing.List`, `Optional` or `Union`.
- No `Any` in domain or use-case signatures. If unavoidable at an SDK boundary, contain it in the adapter.
- `# type: ignore` must name the error code (`# type: ignore[attr-defined]`) and be rare.
- Prefer `Protocol` for ports over abstract base classes. Use `Literal` or `StrEnum` for closed sets of values.

## Data models

- Pydantic v2 for anything crossing a boundary (API, config, LLM output, persisted records). Plain `@dataclass(frozen=True, slots=True)` for internal value objects.
- Make models immutable (`model_config = ConfigDict(frozen=True)`) unless mutation is the point.
- Validate at the edges, then trust types inside. Do not re-validate in every function.
- Secrets use `SecretStr`. Never put a secret in a model's repr, log line or exception message.

## Errors

- Define a project exception hierarchy per area (for example `IngestionError` with `UnsupportedFormatError`, `CorruptDocumentError`). Each has a stable `category` string used in logs, job records and metrics.
- Never use a bare `except:`. Catch `Exception` only at process or request boundaries, and log with `logger.exception`.
- Do not return `None` to signal failure. Raise a typed error or return an explicit result type.
- Chain with `raise NewError(...) from exc` when translating SDK errors.

## Async

- I/O-bound code paths (HTTP, database, model calls) are `async`. Never call blocking I/O inside `async def`. Use an async client, or `asyncio.to_thread` for CPU or blocking work such as parsing PDFs.
- Every external call has a timeout. Use `asyncio.timeout()` where the client has none.
- Use `asyncio.TaskGroup` for concurrent work, not bare `create_task` without awaiting.

## Logging

- `logger = logging.getLogger(__name__)` per module. Never use `print`.
- Pass a constant message and put variables in `extra={...}`: `logger.info("chunks indexed", extra={"document_id": doc_id, "count": n})`. No f-strings in log calls.
- The request ID is attached automatically; do not add it by hand.

## Style

- Functions do one thing. Keep the happy path unindented with early returns.
- Use `pathlib.Path`, not `os.path`. Use `datetime.now(UTC)`, never naive datetimes.
- Constants in `UPPER_SNAKE_CASE` at module level. No magic numbers in logic; move them into settings or named constants.
- Docstrings explain why or contract, not what the code obviously does. Module docstrings for non-trivial modules.
- No mutable default arguments. No wildcard imports. No `global`.
- Dependency injection through constructor or function parameters. No module-level singletons except the cached settings loader.
