from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[3] / "datasets" / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()
