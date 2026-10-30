# ADR-0018: A Next.js web UI for asking and comparing answer modes

- Status: Accepted
- Date: 2026-10-30

## Context

AGENT-01 added a second answer mode, the planned workflow (ADR-0017), to be compared with standard RAG. The user asked for a UI to choose the mode and see both answers side by side, and specified Next.js, pnpm and Tailwind CSS.

The plan defers a sophisticated frontend, and the backend layering (ADR-0002) assumes one Python package. A UI therefore has to stay a thin HTTP client that adds no business rules.

## Options considered

1. **A Next.js app in `web/`**, talking to the API only over HTTP. This is the user's choice: a familiar stack and easy to extend. Cons: a second toolchain (Node, pnpm, its own lockfile and CI job).
2. **A static page served by FastAPI.** No new stack, but harder to grow.
3. **Streamlit or Gradio.** Quick to build, but a heavy dependency, and it bypasses the real HTTP API.

## Decision

Option 1.

- **Versions:**
  - Next.js 16.4.3 (App Router, Cache Components) with React 19, TypeScript, Tailwind CSS 4 and pnpm 11, in `web/`. Versions are locked in `web/pnpm-lock.yaml`.
  - 16 rather than 15: Next 15.5's PostCSS has known advisories whose fix requires 16. `pnpm audit` reports none.
- **Boundary:**
  - The browser calls `/api/*`, which a Next.js rewrite forwards to `EKA_API_URL` (default `http://localhost:8000`). The API needs no CORS change, and the UI holds no secrets.
  - The UI has no server-side logic of its own.
- **Pages:**
  - **Ask:** one question, answered in Direct, Workflow or Compare-both mode. The two modes run concurrently. Each answer shows:
    - its route: Search → Answer, or Plan → Search × n → Answer;
    - the sub-questions the workflow searched;
    - its sources (title, section, page);
    - model calls, steps and measured latency.
  - **Documents:** upload a file, then poll its ingestion job (JOB-01) until it is ready or failed.
- **Identity:** the UI sends the development headers (`X-Tenant-ID`, `X-User-ID`, `X-User-Groups`), set in the header and kept in `localStorage` through `useSyncExternalStore`. The API accepts them only in local and test environments, so the UI is a local tool until SEC-01 adds real sign-in.
- **Design:**
  - Harbour palette: a mist ground, harbour-ink text, teal for direct and bamboo for the workflow.
  - *Be Vietnam Pro* for both languages' diacritics.
  - The route line is the one emphasised element.
  - Responsive to phone width, with visible focus, and motion only under `prefers-reduced-motion: no-preference`.
- **Checks:** `pnpm lint`, `pnpm typecheck`, `pnpm test` (Vitest, covering the API client and route and citation helpers) and `pnpm build`, run by a `web` job in CI.

## Consequences

- **Second toolchain:** Node and pnpm are now project dependencies. `web/` is outside the Python layering, and its import-linter contracts do not apply; it must stay an HTTP client of `/v1`.
- **API changes:** each one now has a second consumer. The TypeScript types in `web/src/lib/api.ts` mirror the response models by hand. Generating them from the OpenAPI schema is worth it if the API grows.
- **Hosting:** not covered here. Week 7 decides whether the UI ships at all, and how, with authentication.
- **Dev origin:** Next 16's dev server refuses hot-reload connections from origins other than `localhost`, so open the UI at `http://localhost:3000`.
