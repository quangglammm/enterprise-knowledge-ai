"""Apply ordered SQL migrations (ADR-0007). Run with ``uv run eka-migrate``.

Each file in ``sql/`` runs once, in its own transaction, recorded in ``schema_migrations``.
An advisory lock makes concurrent runs (for example two containers starting) safe.
"""

import logging
from importlib import resources

import psycopg

from enterprise_knowledge.config import get_settings
from enterprise_knowledge.observability.logging import configure_logging

logger = logging.getLogger(__name__)

# Arbitrary constant shared by every migration run against the same database.
_ADVISORY_LOCK_ID = 7_342_001


def migration_files() -> list[tuple[str, bytes]]:
    """(version, sql) pairs in apply order. Version is the file name without extension."""
    folder = resources.files("enterprise_knowledge.infrastructure.postgres").joinpath("sql")
    files = sorted((f for f in folder.iterdir() if f.name.endswith(".sql")), key=lambda f: f.name)
    return [(f.name.removesuffix(".sql"), f.read_bytes()) for f in files]


def migrate(conninfo: str) -> list[str]:
    """Apply pending migrations and return the versions applied in this run."""
    applied_now: list[str] = []
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version text PRIMARY KEY,"
            " applied_at timestamptz NOT NULL DEFAULT now())"
        )
        conn.execute("SELECT pg_advisory_lock(%s)", (_ADVISORY_LOCK_ID,))
        try:
            done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
            for version, sql in migration_files():
                if version in done:
                    continue
                with conn.transaction():
                    conn.execute(sql)
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
                logger.info("migration applied", extra={"migration": version})
                applied_now.append(version)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_LOCK_ID,))
    return applied_now


def wipe_documents(conninfo: str) -> None:
    """Delete every document and chunk. Only for disposable databases (tests, benchmarks)."""
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("TRUNCATE documents, chunks CASCADE")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    applied = migrate(settings.database_url.get_secret_value())
    logger.info("migrations complete", extra={"applied": len(applied)})


if __name__ == "__main__":
    main()
