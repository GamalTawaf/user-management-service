from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError

from app.audit.router import router as audit_router
from app.intake.router import router as intake_router
from app.prior_auth.router import router as prior_auth_router
from app.shared.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailure,
    bad_request_handler,
    conflict_handler,
    forbidden_handler,
    http_exception_handler,
    not_found_handler,
    request_validation_handler,
    validation_failure_handler,
)
from app.shared.middleware import TRACE_ID_HEADER, LimitRequestBodyMiddleware, TraceIdMiddleware
from app.telemetry import setup_telemetry

_TRACE_ID_OPENAPI = {
    TRACE_ID_HEADER: {
        "description": (
            "Request correlation id. Echoed from the request header when provided; "
            "otherwise minted per request."
        ),
        "schema": {"type": "string", "example": "a1b2c3d4e5f64789a1b2c3d4e5f64789"},
    }
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_telemetry(app)
    yield


app = FastAPI(
    title="Prior Authorization API",
    version="0.1.0",
    lifespan=lifespan,
    description=(
        "Partner-facing prior authorization API. "
        "People: members (patients), provider offices (doctors' offices), "
        "reviewers (nurses or physicians), operations admins, auditors. "
        "JSON/API field names stay technical (`member_id`, role enums); "
        "office emails use plain language. Primary keys are named `uuid`. "
        "Errors use `error_code`, `field`, `message`, and optional `correlation_id`. "
        f"Every response includes `{TRACE_ID_HEADER}` (send the same header to correlate retries)."
    ),
)

# TraceId outermost so early LimitRequestBody 413s still get the header.
app.add_middleware(LimitRequestBodyMiddleware)
app.add_middleware(TraceIdMiddleware)
app.add_exception_handler(ValidationFailure, validation_failure_handler)
app.add_exception_handler(RequestValidationError, request_validation_handler)
app.add_exception_handler(BadRequestError, bad_request_handler)
app.add_exception_handler(ConflictError, conflict_handler)
app.add_exception_handler(NotFoundError, not_found_handler)
app.add_exception_handler(ForbiddenError, forbidden_handler)
app.add_exception_handler(HTTPException, http_exception_handler)

app.include_router(prior_auth_router)
app.include_router(intake_router)
app.include_router(audit_router)


@app.get("/v1/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


def _annotate_openapi_trace_headers(schema: dict) -> None:
    paths = schema.get("paths") or {}
    for path_item in paths.values():
        for method in _HTTP_METHODS:
            operation = path_item.get(method)
            if operation is None:
                continue
            responses = operation.get("responses") or {}
            for response in responses.values():
                headers = response.setdefault("headers", {})
                headers[TRACE_ID_HEADER] = _TRACE_ID_OPENAPI[TRACE_ID_HEADER]


def _build_openapi() -> dict:
    from fastapi.openapi.utils import get_openapi

    if app.openapi_schema is not None:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    _annotate_openapi_trace_headers(schema)
    app.openapi_schema = schema
    return schema


app.openapi = _build_openapi  # type: ignore[method-assign]
