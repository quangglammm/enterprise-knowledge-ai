"""PreToolUse hook: block git commits that break the project's message convention.

Enforces what CLAUDE.md asks for: a single-line Conventional Commits message with no
Claude/Anthropic attribution trailers. Exit code 2 blocks the Bash call and shows the
reason to Claude. Standard library only.
"""

import json
import re
import shlex
import sys

CONVENTIONAL = re.compile(
    r"^(feat|fix|refactor|test|docs|chore|ci|perf|build|revert)(\([a-z0-9-]+\))?!?: \S.{0,70}$"
)
FORBIDDEN = re.compile(r"co-authored-by|claude-session|generated with|anthropic\.com", re.I)


def is_git_commit(tokens: list[str]) -> bool:
    """True if some `git` invocation's subcommand (first non-option token) is `commit`."""
    for i, word in enumerate(tokens):
        if word != "git":
            continue
        j = i + 1
        while j < len(tokens) and tokens[j].startswith("-"):
            j += 2 if tokens[j] in ("-C", "-c") else 1
        if j < len(tokens) and tokens[j] == "commit":
            return True
    return False


def extract_messages(command: str) -> list[str] | None:
    """Return -m/--message values of a git commit, or None if it is not a git commit."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []  # heredoc or unbalanced quotes: inspect raw text only
    if not is_git_commit(tokens):
        return None
    messages: list[str] = []
    for i, token in enumerate(tokens):
        if token in ("-m", "--message") and i + 1 < len(tokens):
            messages.append(tokens[i + 1])
        elif token.startswith("--message="):
            messages.append(token.split("=", 1)[1])
    return messages


def block(reason: str) -> int:
    print(f"Commit blocked: {reason}", file=sys.stderr)
    print('Use one line, e.g. git commit -m "feat(ingestion): parse pdf fixtures"', file=sys.stderr)
    return 2


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    command = (event.get("tool_input") or {}).get("command") or ""
    if not re.search(r"\bgit\b.*\bcommit\b", command, re.S):
        return 0

    if FORBIDDEN.search(command):
        return block("attribution trailers (Co-Authored-By, Claude-Session, ...) are not allowed.")

    messages = extract_messages(command)
    if messages is None:
        return 0
    if "--amend" in command and "--no-edit" in command and not messages:
        return 0
    if len(messages) != 1:
        return block("pass exactly one -m with a single-line message (no -F, heredoc or body).")
    message = messages[0]
    if "\n" in message.strip():
        return block("message must be a single line.")
    if not CONVENTIONAL.match(message.strip()):
        return block(f"not Conventional Commits style or over 72 chars: {message!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
