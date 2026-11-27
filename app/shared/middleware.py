from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings

TRACE_ID_HEADER = "X-Trace-Id"
_MAX_TRACE_ID_LEN = 128


def resolve_trace_id(request: Request) -> str:
    raw = request.headers.get(TRACE_ID_HEADER)
    if raw is not None:
        cleaned = raw.strip()
        if cleaned and len(cleaned) <= _MAX_TRACE_ID_LEN:
            return cleaned
    return uuid.uuid4().hex


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Echo or mint `X-Trace-Id` on every response (including early rejects)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = resolve_trace_id(request)
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers[TRACE_ID_HEADER] = trace_id
        return response


class LimitRequestBodyMiddleware(BaseHTTPMiddleware):
    """Reject oversized bodies early (mirror this limit on any reverse proxy)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        header = request.headers.get("content-length")
        if (
            header is not None
            and header.isdigit()
            and int(header) > settings.max_request_body_bytes
        ):
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large"},
            )
        return await call_next(request)
