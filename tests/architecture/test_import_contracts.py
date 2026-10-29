"""Architecture guard (ADR-0002): the import graph must satisfy the contracts in pyproject.toml.

Runs as part of the default test suite so a layering violation fails `pytest`, not just CI.
import-linter runs in a subprocess: in-process it reconfigures logging with dictConfig,
which disables already-created loggers and breaks unrelated tests.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINT_IMPORTS = Path(sys.executable).parent / "lint-imports"


def test_import_contracts_are_kept() -> None:
    result = subprocess.run(  # noqa: S603 - fixed executable from this environment
        [str(LINT_IMPORTS), "--no-cache", "--config", str(ROOT / "pyproject.toml")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert result.returncode == 0, f"Architecture contracts broken:\n{result.stdout}{result.stderr}"
