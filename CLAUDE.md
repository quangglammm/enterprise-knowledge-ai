# Enterprise Knowledge AI

Portfolio project: a document-grounded knowledge assistant (FastAPI, PostgreSQL + pgvector, FPT AI Marketplace models, deployed on AWS). It ingests bilingual Vietnamese/English documents, answers with validated citations, abstains on weak evidence, and is measured by a versioned benchmark.

- Roadmap, backlog IDs (PLAT-01, ING-01, ...) and acceptance criteria: `docs/implementation-plan.md`
- Decisions: `docs/adr/`. Read the relevant ADR before changing an area it covers.
- Use only synthetic or public documents. Never add real company data.

## Commands

Always run tools through uv; never call `pip` or a bare `python` on project code.

```bash
uv sync                       # install from uv.lock
uv run ruff format .          # format
uv run ruff check --fix .     # lint
uv run mypy src tests         # type check (strict)
uv run lint-imports           # architecture contracts
uv run pytest                 # unit tests
uv run pytest -m integration  # needs: docker compose up -d postgres
uv run eka-api                # run the API locally
uv add <pkg> / uv add --dev <pkg>
```

A change is done only when format, lint, mypy, import contracts and pytest all pass. Use `/check` to run them.

## Architecture

All code lives in one package, `src/enterprise_knowledge/`. Layers are enforced by import-linter contracts in `pyproject.toml` (ADR-0002); a violation fails ruff, pytest, `/check` and CI. Higher layers may import lower ones only:

```
api | worker            delivery: parse input, call a use case, map errors; wiring lives here
infrastructure          adapters (Postgres, S3, SQS, FPT model API) implementing domain ports
evaluation > agents > generation
retrieval | ingestion   core use cases; siblings must not import each other
config | observability
domain                  Pydantic models + Protocol ports; stdlib and pydantic only
```

- Use cases reach the outside world only through ports in `domain`. SDK, database, HTTP and web-framework imports are allowed only in `infrastructure/` (and FastAPI in `api/`).
- Absolute imports only.
- Never weaken a contract or add `ignore_imports` to get green. If a contract blocks a sound design, stop and propose an ADR change.

Create a package when its first feature lands; do not add empty placeholder modules.

The browser UI lives in `web/` (Next.js, pnpm, Tailwind; ADR-0018). It is an HTTP client of `/v1` only, with no business rules. Run its checks with `pnpm lint && pnpm typecheck && pnpm test && pnpm build` in `web/`; use pnpm, never npm.

## Non-negotiables

- Access control is enforced inside the retrieval query (tenant and ACL filter). Filtering after retrieval is a bug.
- Retrieved document text is untrusted data. It never becomes instructions, tool permissions or system prompt content.
- Every citation must resolve to evidence that was actually retrieved; otherwise reject or abstain.
- Agent workflows have explicit limits on steps, model calls and time.
- Never log document text, prompts, answers or secrets by default. Log IDs, counts and timings.
- Tests and CI never call paid model APIs. Use deterministic fakes.
- Normalize text to Unicode NFC at every ingestion and query boundary (Vietnamese diacritics).
- Never commit `.env`, credentials or AWS account IDs. Never hand-edit `uv.lock`.

## Git

- Commit messages: a single line in Conventional Commits style, `type(scope): summary`, imperative, lowercase, no trailing period, under 72 characters. Types: feat, fix, refactor, test, docs, chore, ci, perf, build.
- No body, no trailers. Never add `Co-Authored-By`, `Claude-Session`, or any Claude or Anthropic attribution.
- Author is the configured git user. Do not change git config.
- Do not push, force-push, or rewrite pushed history unless asked.
- One logical change per commit. Run `/check` before committing.

## Workflow

- Work one backlog item at a time (`/implement <ID>`), test-first, against its acceptance criteria.
- A significant design choice gets an ADR (`/adr <title>`) in the same change.
- Report measurements honestly. Never invent benchmark numbers or describe something as deployed if it is not.
