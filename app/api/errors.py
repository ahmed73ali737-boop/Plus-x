"""Presentation-layer mapping of domain error categories to HTTP responses."""
from __future__ import annotations

from fastapi.responses import JSONResponse

from app.domain.errors import DomainError

HTTP_STATUS_BY_KIND = {
    'invalid': 422,
    'unauthenticated': 401,
    'forbidden': 403,
    'not_found': 404,
    'conflict': 409,
    'gone': 410,
    'precondition_required': 428,
    'rate_limited': 429,
    'unavailable': 503,
}


def http_status(error: DomainError) -> int:
    return HTTP_STATUS_BY_KIND[error.kind]


def error_response(error: DomainError) -> JSONResponse:
    """Same body shape FastAPI uses for HTTPException: {"detail": <code>}."""
    return JSONResponse({'detail': error.code}, status_code=http_status(error))


def install_error_handlers(app) -> None:
    @app.exception_handler(DomainError)
    async def domain_error_handler(_request, error: DomainError):
        return error_response(error)
