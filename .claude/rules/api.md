---
paths:
  - "src/enterprise_knowledge/api/**/*.py"
---

# API layer

- Route handlers only parse input, call one use case, and map the result. No SQL, SDK calls or business rules in a handler.
- Every endpoint declares request and response Pydantic models and its error responses (`responses={...}`) so the OpenAPI schema is complete.
- Inject dependencies with `Depends`, wired in the app factory. Tests override them via the factory's parameters or `app.dependency_overrides`.
- Map domain errors to HTTP in one exception-handler module. Error bodies use a stable shape: `{"error": {"category": ..., "message": ..., "request_id": ...}}`. Never return stack traces or internal exception text.
- Uploads: enforce size limits and allowed content types before reading the body fully. Never trust the client-supplied filename for paths.
- Long-running work (ingestion) returns `202 Accepted` with a job ID; it is never done inside the request.
- Version public routes under `/v1`. Health endpoints stay unversioned.
