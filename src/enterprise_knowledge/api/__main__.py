"""Entry point: ``uv run eka-api`` or ``python -m enterprise_knowledge.api``."""

import uvicorn

from enterprise_knowledge.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "enterprise_knowledge.api.app:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,  # our configure_logging() owns the handlers
    )


if __name__ == "__main__":
    main()
