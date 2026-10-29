---
name: review-code
description: Critically review the current diff or a given path against the project rules (layering, typing, error handling, tests, GenAI safety) and report findings by severity. Use before committing a feature or when asked for a code review.
argument-hint: "[path | staged | HEAD~n]"
allowed-tools: Read Glob Grep Bash(git diff *) Bash(git log *) Bash(git status *)
context: fork
---

Scope: $ARGUMENTS (default: all uncommitted changes, `git diff HEAD`).

Read the changed files in full, not only the hunks, plus `CLAUDE.md` and the `.claude/rules/` files that match their paths. Check:

1. **Correctness:** logic errors, unhandled edge cases, off-by-one in chunking or ranking, wrong async usage (blocking calls in `async def`, missing awaits, unbounded concurrency).
2. **Layering:** domain importing infrastructure or SDKs; business logic in API handlers or adapters; concrete adapters used inside use cases.
3. **Types and errors:** `Any` leaking into core code, untyped `# type: ignore`, broad `except`, errors without a stable category, `None` used as a failure signal.
4. **Security and GenAI safety:** ACL filtering after retrieval, retrieved text reaching instructions, unverified citations, unbounded retries or agent loops, missing timeouts, secrets or document text in logs.
5. **Tests:** acceptance criteria without a test, missing negative cases, mocks of ports where a fake belongs, assertions on implementation details, nondeterminism.
6. **Operations:** new settings missing from `.env.example`, new dependencies without justification, docs or ADR not updated.

Report as a table: severity (blocker, major, minor, nit), file:line, finding, suggested fix. Then list anything done well that should be kept. Do not edit files; this skill only reports. If there are no blockers or majors, say so plainly.
