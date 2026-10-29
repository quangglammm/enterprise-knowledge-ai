---
name: commit
description: Commit the current changes with a one-line Conventional Commits message and no Claude attribution, after the quality gate passes.
argument-hint: "[optional summary hint]"
disable-model-invocation: true
allowed-tools: Bash(git status *) Bash(git diff *) Bash(git add *) Bash(git commit *) Bash(git log *)
---

1. Run `git status` and `git diff` (staged and unstaged). If the changes mix unrelated concerns, propose how to split them into separate commits and ask before continuing.
2. Make sure `/check` has passed for this change. If it has not been run since the last edit, run it now.
3. Check the diff for anything that must not be committed: `.env` files, credentials, AWS account IDs, real company documents, large binaries, debug prints. Stop and report if found.
4. Stage only the files for this change by path. Never use `git add -A` blindly when unrelated files are modified.
5. Commit with exactly one line:

   ```
   git commit -m "<type>(<scope>): <summary>"
   ```

   - type: feat, fix, refactor, test, docs, chore, ci, perf, build
   - scope: the area, such as api, ingestion, retrieval, generation, agents, eval, infra, deps. Omit when the change is repo-wide.
   - summary: imperative, lowercase, no trailing period, whole line under 72 characters.
   - Reference the backlog ID when there is one: `feat(ingestion): parse pdf, docx and html fixtures (ING-01)`.
   - No body. No trailers. Never add `Co-Authored-By`, `Claude-Session`, "Generated with", or any Claude or Anthropic attribution.

6. Show `git log --oneline -3`. Do not push unless the user asks.

User hint for the summary, if any: $ARGUMENTS
