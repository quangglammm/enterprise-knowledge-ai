"""Entry point: ``uv run eka-worker`` or ``python -m enterprise_knowledge.worker``."""

import asyncio

from enterprise_knowledge.config import get_settings
from enterprise_knowledge.worker.app import run


def main() -> None:
    asyncio.run(run(get_settings()))


if __name__ == "__main__":
    main()
