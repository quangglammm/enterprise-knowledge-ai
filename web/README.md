# Web UI

A Next.js app for asking the knowledge API questions and comparing direct RAG with the
planned workflow side by side, plus uploading documents and watching their ingestion jobs
(ADR-0018). It talks to the FastAPI server only over HTTP: `/api/*` is rewritten to
`EKA_API_URL` (default `http://localhost:8000`).

```bash
pnpm install
pnpm dev          # http://localhost:3000, with the API and worker running (docker compose up)
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

It sends the development identity headers, which the API accepts only in local and test
environments; set the tenant, user and groups from the header.
