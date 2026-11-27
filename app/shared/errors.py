from __future__ import annotations

import contextlib
import uuid
from typing import Any, NoReturn

import jwt
from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class FieldError(BaseModel):
    error_code: str
    field: str
    message: str


def field_errors_from_pydantic(errors: list[Any]) -> list[FieldError]:
    mapped: list[FieldError] = []
    for err in errors:
        loc = err.get("loc", ())
        parts = [str(part) for part in loc if part != "body"]
        field = ".".join(parts) if parts else "body"
        raw_message = err.get("msg") or "Invalid value"
        message = raw_message if isinstance(raw_message, str) else repr(raw_message)
        mapped.append(
            FieldError(
                error_code="invalid_type",
                field=field,
                message=message,
            )
        )
    return mapped


class ProblemBody(BaseModel):
    """Partner-facing error envelope (422 intake, 400, and structured 409)."""

    detail: str
    errors: list[FieldError] = Field(default_factory=list)
    correlation_id: str | None = None


# OpenAPI — applied on partner routers so Swagger matches live ProblemBody envelope.
IDEMPOTENCY_KEY_REUSE_EXAMPLE = {
    "detail": "Idempotency-Key was already used with a different request body",
    "errors": [
        {
            "error_code": "idempotency_key_reuse",
            "field": "Idempotency-Key",
            "message": "Same Idempotency-Key must replay the same request body",
        }
    ],
}

OPENAPI_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "description": "Bad request (e.g. invalid Idempotency-Key)",
        "model": ProblemBody,
    },
    401: {
        "description": "Missing or invalid bearer token",
        "model": ProblemBody,
    },
    403: {
        "description": "Forbidden (role or conflict-of-interest)",
        "model": ProblemBody,
    },
    404: {
        "description": "Resource not found",
        "model": ProblemBody,
    },
    409: {
        "description": "Conflict (e.g. idempotency_key_reuse, already claimed)",
        "model": ProblemBody,
        "content": {
            "application/json": {
                "example": IDEMPOTENCY_KEY_REUSE_EXAMPLE,
            }
        },
    },
    422: {
        "description": (
            "Validation failed — `errors[]` with `error_code` / `field` / `message`; "
            "submit may include `correlation_id` for support lookup"
        ),
        "model": ProblemBody,
    },
}


class ValidationFailure(Exception):
    def __init__(
        self, correlation_id: str, errors: list[FieldError], detail: str = "Validation failed"
    ):
        self.correlation_id = correlation_id
        self.errors = errors
        self.detail = detail
        super().__init__(detail)


def raise_validation(
    errors: list[FieldError],
    *,
    correlation_id: str | None = None,
    detail: str = "Validation failed",
) -> NoReturn:
    cid = correlation_id or uuid.uuid4().hex
    raise ValidationFailure(correlation_id=cid, errors=errors, detail=detail)


def raise_field(error_code: str, field: str, message: str) -> NoReturn:
    raise_validation([FieldError(error_code=error_code, field=field, message=message)])


class BadRequestError(Exception):
    def __init__(
        self,
        errors: list[FieldError],
        detail: str = "Bad request",
    ):
        self.errors = errors
        self.detail = detail
        super().__init__(detail)


def raise_bad_request(errors: list[FieldError], *, detail: str = "Bad request") -> NoReturn:
    raise BadRequestError(errors=errors, detail=detail)


class ConflictError(Exception):
    def __init__(self, detail: str = "Conflict", *, errors: list[FieldError] | None = None):
        self.detail = detail
        self.errors = errors or []
        super().__init__(detail)


class NotFoundError(Exception):
    def __init__(self, detail: str = "Not found"):
        self.detail = detail
        super().__init__(detail)


class ForbiddenError(Exception):
    def __init__(self, detail: str = "Forbidden"):
        self.detail = detail
        super().__init__(detail)


async def validation_failure_handler(_request: Request, exc: ValidationFailure) -> JSONResponse:
    body = ProblemBody(
        detail=exc.detail,
        errors=exc.errors,
        correlation_id=exc.correlation_id,
    )
    payload = body.model_dump()
    return JSONResponse(status_code=422, content=payload)


def _db_from_request(request: Request):
    from app.db import get_db

    factory = request.app.dependency_overrides.get(get_db, get_db)
    gen = factory()
    session = next(gen)
    return session, gen


def _office_context_from_request(request: Request, db):
    """Best-effort actor for durable intake rejects on schema failures."""
    from app.config import settings
    from app.identity.models import User, UserRole
    from app.identity.schemas import UserContext

    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1]
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = uuid.UUID(data["sub"])
    except jwt.PyJWTError, KeyError, ValueError, TypeError:
        return None
    user = db.get(User, user_id)
    if user is None or user.role != UserRole.provider_office or user.practice_id is None:
        return None
    return UserContext(
        user_id=user.uuid,
        role=user.role,
        practice_id=user.practice_id,
        member_id=user.member_id,
        email=user.email,
    )


def _persist_submit_schema_rejection(
    request: Request, exc: RequestValidationError, errors: list[FieldError]
) -> str | None:
    from app.intake.persist import persist_intake_rejection

    db, gen = _db_from_request(request)
    try:
        ctx = _office_context_from_request(request, db)
        if ctx is None or ctx.practice_id is None:
            return None
        raw = exc.body if isinstance(exc.body, dict) else {}
        return persist_intake_rejection(
            db,
            actor_user_id=ctx.user_id,
            practice_id=ctx.practice_id,
            payload=raw,
            errors=errors,
        )
    finally:
        with contextlib.suppress(StopIteration):
            next(gen)


async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    pydantic_errors = exc.errors()
    errors = field_errors_from_pydantic(pydantic_errors)
    correlation_id: str | None = None
    is_submit = request.method == "POST" and request.url.path.rstrip("/") == "/v1/prior-auths"
    if is_submit and errors:
        with contextlib.suppress(Exception):
            correlation_id = _persist_submit_schema_rejection(request, exc, errors)
    if correlation_id is None:
        correlation_id = uuid.uuid4().hex
    body = ProblemBody(
        detail="Validation failed",
        errors=errors,
        correlation_id=correlation_id,
    )
    content = body.model_dump()
    return JSONResponse(status_code=422, content=content)


async def bad_request_handler(_request: Request, exc: BadRequestError) -> JSONResponse:
    body = ProblemBody(detail=exc.detail, errors=exc.errors)
    content = body.model_dump()
    return JSONResponse(status_code=400, content=content)


async def conflict_handler(_request: Request, exc: ConflictError) -> JSONResponse:
    body = ProblemBody(detail=exc.detail, errors=exc.errors)
    content = body.model_dump()
    return JSONResponse(status_code=409, content=content)


async def not_found_handler(_request: Request, exc: NotFoundError) -> JSONResponse:
    body = ProblemBody(detail=exc.detail)
    content = body.model_dump()
    return JSONResponse(status_code=404, content=content)


async def forbidden_handler(_request: Request, exc: ForbiddenError) -> JSONResponse:
    body = ProblemBody(detail=exc.detail)
    content = body.model_dump()
    return JSONResponse(status_code=403, content=content)


async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    """Wrap auth/role HTTPException detail strings in the same ProblemBody envelope."""
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    body = ProblemBody(detail=detail)
    content = body.model_dump()
    return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)
