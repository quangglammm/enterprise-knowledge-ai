"""Structured logging with request correlation.

Every log record carries the current request ID (set by the API middleware, and later by
the worker per job), so one ID connects API, retrieval, model and workflow events (OBS-01).
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else was passed via ``extra=`` and is emitted.
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        payload.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED})
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


# request_id is emitted explicitly; color_message is uvicorn's ANSI duplicate of message.
_RESERVED |= {"request_id", "color_message"}


def _install_request_id_factory() -> None:
    """Stamp the current request ID onto every record at creation time.

    Doing it in the record factory (not a handler filter) means every handler, including
    test capture handlers, sees the ID even if the record is formatted after the request.
    """
    base_factory = logging.getLogRecordFactory()
    if getattr(base_factory, "_eka_request_id", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = base_factory(*args, **kwargs)
        record.request_id = request_id_var.get()
        return record

    factory._eka_request_id = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    _install_request_id_factory()
    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s")
        )

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Uvicorn's access log duplicates our request log; keep its error logger.
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False
