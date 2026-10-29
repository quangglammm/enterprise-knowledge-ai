---
name: check
description: Run the project quality gate (ruff format, ruff lint, mypy strict, import-linter architecture contracts, pytest) and fix failures. Use before every commit and whenever a change is claimed to be done.
argument-hint: "[--integration]"
allowed-tools: Bash(uv run ruff *) Bash(uv run mypy *) Bash(uv run lint-imports *) Bash(uv run pytest *) Bash(uv sync *) Bash(uv lock --check)
---

Run these in order from the repository root. Stop at the first step that fails, fix the cause, and restart from step 1.

1. `uv lock --check` (lockfile matches pyproject.toml; if not, run `uv lock` and include it in the change)
2. `uv run ruff format .`
3. `uv run ruff check --fix .`
4. `uv run mypy src tests`
5. `uv run lint-imports`
6. `uv run pytest -q`
7. Only if `$ARGUMENTS` contains `--integration`: `uv run pytest -m integration -q` (requires `docker compose up -d postgres`)

Fixing rules:

- Fix the code, not the check. Do not add `# noqa`, `# type: ignore`, `pytest.skip`, `ignore_imports`, or loosen ruff, mypy or import-linter settings to get green. An architecture violation is fixed by moving code to the right layer or introducing a port, per ADR-0002. If one seems truly necessary, stop and explain why to the user first.
- Do not delete or weaken an existing assertion to make a test pass. If a test is wrong, say so and explain.
- A flaky test is a bug. Report it rather than re-running until it passes.

Finish with one line per step: pass or fail, and for failures what you changed.
