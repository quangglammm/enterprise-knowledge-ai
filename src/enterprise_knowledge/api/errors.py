"""One error shape for every failure: {"error": {"category", "message", "request_id"}}.

Domain errors map to HTTP statuses here and only here. Unexpected errors return a generic
message; details stay in the logs.
"""

import logging
from typing import ClassVar

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from enterprise_knowledge.domain.errors import (
    AccessViolationError,
    DocumentNotFoundError,
    DomainError,
)
from enterprise_knowledge.ingestion.errors import (
    DocumentTooLargeError,
    IngestionError,
    UnsupportedFormatError,
)
from enterprise_knowledge.observability.logging import request_id_var
from enterprise_knowledge.retrieval.errors import InvalidQueryError

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """Errors raised by the HTTP layer itself (authentication, authorization of a request)."""

    status_code: ClassVar[int] = status.HTTP_400_BAD_REQUEST
    category: ClassVar[str] = "bad_request"


class AuthenticationError(ApiError):
    status_code: ClassVar[int] = status.HTTP_401_UNAUTHORIZED
    category: ClassVar[str] = "unauthenticated"


class ForbiddenError(ApiError):
    status_code: ClassVar[int] = status.HTTP_403_FORBIDDEN
    category: ClassVar[str] = "forbidden"


class ServiceUnavailableError(ApiError):
    status_code: ClassVar[int] = status.HTTP_503_SERVICE_UNAVAILABLE
    category: ClassVar[str] = "service_unavailable"


_DOMAIN_STATUS: list[tuple[type[DomainError], int]] = [
    (DocumentTooLargeError, status.HTTP_413_CONTENT_TOO_LARGE),
    (UnsupportedFormatError, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE),
    (IngestionError, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (InvalidQueryError, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (DocumentNotFoundError, status.HTTP_404_NOT_FOUND),
]


def error_response(status_code: int, category: str, message: str) -> JSONResponse:
    body = {"error": {"category": category, "message": message, "request_id": request_id_var.get()}}
    return JSONResponse(status_code=status_code, content=body)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status_code, exc.category, str(exc))

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        if isinstance(exc, AccessViolationError):
            # An adapter returned forbidden content: a bug. Never echo details to the caller.
            logger.error("access violation blocked", extra={"category": exc.category})
            return error_response(500, "internal_error", "internal error")
        for error_type, status_code in _DOMAIN_STATUS:
            if isinstance(exc, error_type):
                return error_response(status_code, exc.category, str(exc))
        logger.exception("unmapped domain error", extra={"category": exc.category})
        return error_response(500, "internal_error", "internal error")

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = sorted({".".join(str(p) for p in err["loc"][1:]) for err in exc.errors()})
        return error_response(422, "invalid_request", f"invalid fields: {', '.join(fields)}")

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        category = "not_found" if exc.status_code == 404 else "http_error"
        return error_response(exc.status_code, category, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error")
        return error_response(500, "internal_error", "internal error")
