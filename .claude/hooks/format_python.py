"""PostToolUse hook: format and lint a Python file right after Claude edits it.

Reads the hook event JSON on stdin. For .py files inside the project it runs
``ruff format`` and ``ruff check --fix``. Remaining lint errors are written to stderr
with exit code 2, which Claude Code shows to Claude so it fixes them immediately.
Standard library only, so it runs before ``uv sync`` has happened.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    file_path = (event.get("tool_input") or {}).get("file_path")
    if not file_path or not file_path.endswith(".py"):
        return 0

    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or ".").resolve()
    target = Path(file_path).resolve()
    if project not in target.parents or not target.exists():
        return 0

    def ruff(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - fixed command, path checked above
            ["uv", "run", "--quiet", "ruff", *args, str(target)],  # noqa: S607
            cwd=project,
            capture_output=True,
            text=True,
            check=False,
        )

    try:
        ruff("format", "--quiet")
        result = ruff("check", "--fix", "--quiet")
    except FileNotFoundError:
        print("uv not found; skipped ruff", file=sys.stderr)
        return 1

    if result.returncode != 0:
        print(f"ruff found issues in {target.relative_to(project)}:", file=sys.stderr)
        print(result.stdout.strip() or result.stderr.strip(), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
