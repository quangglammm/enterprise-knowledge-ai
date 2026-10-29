---
name: implement
description: Implement one backlog item from docs/implementation-plan.md (for example ING-01, RAG-02) test-first against its acceptance criteria. Use when the user names a backlog ID or asks for the next task.
argument-hint: "<backlog-id | next>"
---

Target: $ARGUMENTS

## 1. Understand

- Read the item's row in `docs/implementation-plan.md` (backlog table and the matching week), plus any "Revisions" entries that touch it. If the argument is `next`, pick the first item whose dependencies are done and confirm the choice with the user.
- Read the ADRs in `docs/adr/` that cover the area, and the existing code it builds on.
- Restate the acceptance criteria as a numbered list of testable behaviors. Add the negative cases required by `.claude/rules/testing.md`.
- If the item needs a design decision not covered by an ADR (schema shape, library choice, algorithm), present 2–3 options with trade-offs and a recommendation, and wait for the user's choice. Record the decision with `/adr`.

## 2. Plan

Post a short plan: files to add or change, new ports or models, new dependencies (with why), and the test list. Keep the slice small enough to finish in one sitting (roughly 2–6 hours of human work). If it is larger, propose a split.

## 3. Build, test-first

For each behavior on the list:

1. Write the failing test.
2. Run it and confirm it fails for the expected reason.
3. Implement the minimum to pass, respecting the layer rules in `CLAUDE.md`.
4. Run the test again.

Add fakes to `tests/fakes/` rather than mocking ports inline. Add dependencies only with `uv add`.

## 4. Finish

- Run `/check` until green.
- Update docs touched by the change: README commands or endpoints, `.env.example` for new settings, ADR if a decision was made.
- Summarize for the user: which acceptance criteria are met and the test that proves each, anything deferred and why, and a proposed one-line commit message. Do not commit until the user says so (then use `/commit`).
