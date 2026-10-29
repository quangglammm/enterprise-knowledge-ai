# ADR-0002: Enforced layered (clean) architecture

- Status: Accepted
- Date: 2026-10-29

## Context

Much of the code will be written with an AI coding assistant. Instructions in `CLAUDE.md` and `.claude/rules/` describe the layering, but they are advisory: nothing stops a generated change from calling boto3 inside a use case or importing an adapter from the domain. Such violations are cheap to make and expensive to unwind, and they break the main promise of the design: business logic tested with deterministic fakes and infrastructure swappable (pgvector to a managed store, local queue to SQS, one model to another).

## Options considered

1. **Conventions only** (`CLAUDE.md`, code review). Pros: no tooling. Cons: violations surface late, if at all.
2. **Ruff banned imports (TID251) with per-directory ignores.** Pros: instant feedback in the editor and the post-edit hook. Cons: per-file only; cannot express "domain must not import infrastructure" or sibling independence; ignores are per rule, not per banned module.
3. **import-linter contracts over the full import graph.** Pros: expresses layers, independence and forbidden imports, including indirect paths. Cons: runs on the whole package (about a second); `pkg.**` wildcards skip the package's own `__init__.py`.
4. **Hexagonal packaging with separate distributions per layer.** Pros: the strongest boundary. Cons: heavy for a single-service portfolio project.

## Decision

Use options 2 and 3 together. import-linter is authoritative; ruff gives fast feedback and covers `__init__.py`.

Layers, highest first. A layer may import only layers below it; `|` siblings must not import each other.

| Layer | Packages | May depend on |
| --- | --- | --- |
| Delivery | `api` \| `worker` | everything below; wires adapters into use cases |
| Adapters | `infrastructure` | ports in `domain`, settings |
| Orchestration | `evaluation`, then `agents`, then `generation` | lower use cases, ports |
| Core use cases | `retrieval` \| `ingestion` | `domain`, `config`, `observability` |
| Cross-cutting | `config` \| `observability` | `domain` |
| Domain | `domain` | Pydantic and the standard library only |

Additional contracts:

- `domain` must not import web frameworks, AWS SDKs, database drivers, HTTP clients or model SDKs.
- Use-case packages must not import those either; they reach the outside world only through `Protocol` ports in `domain`.
- Relative imports are banned (TID252) so the graph reads unambiguously.

Contracts live in `pyproject.toml` under `[tool.importlinter]`. Packages that do not exist yet are optional, so contracts apply the moment a package is created.

Enforcement points: the ruff post-edit hook (immediate), `tests/architecture/` in the default `pytest` run, `/check`, and CI.

## Consequences

- An adapter is the only place an SDK import is allowed. Each new external dependency needs a port in `domain` and a fake in `tests/fakes/`.
- Composition happens only in `api` and `worker`, which is where tests substitute fakes.
- If a contract blocks a legitimate design, change the contract in a reviewed commit and amend this ADR. Never add `ignore_imports` exceptions silently.
- Revisit if the layer list grows past about eight packages, or if `infrastructure` starts needing to import use cases; that would suggest splitting by bounded context instead.
