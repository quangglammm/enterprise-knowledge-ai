---
name: adr
description: Record an architecture decision as the next numbered ADR in docs/adr/ and link it from the README. Use when a design choice is made about schema, storage, models, libraries, infrastructure or security boundaries.
argument-hint: "<decision title>"
allowed-tools: Read Glob Write Edit
---

Title: $ARGUMENTS

1. List `docs/adr/` and take the next number (zero-padded to 4 digits). File name: `NNNN-kebab-case-title.md`.
2. Fill this template. Be concrete: name versions, numbers, limits, and the alternatives actually considered. Keep it under about 60 lines.

```markdown
# ADR-NNNN: <Title>

- Status: Proposed | Accepted | Superseded by ADR-XXXX
- Date: <today, YYYY-MM-DD>

## Context

<The requirement or problem, the constraints (cost, local dev, testability, the target role), and what forces the decision now.>

## Options considered

1. **<Option>**: <how it works>. Pros: ... Cons: ...
2. **<Option>**: ...

## Decision

<The chosen option and the specific settings or rules that follow from it.>

## Consequences

- <What becomes easier, what becomes harder, what is now required of the code.>
- <How we would know the decision was wrong, and what would trigger revisiting it.>
```

3. If the user has not chosen between options, set Status to Proposed and ask. Do not invent a decision.
4. If it supersedes an earlier ADR, update that ADR's Status line.
5. Add a link under "Plan and architecture decisions" in `README.md`.
6. If the decision changes an item in `docs/implementation-plan.md`, update the "Revisions" section to point to the ADR.
