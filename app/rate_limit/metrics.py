"""OpenTelemetry metrics + helpers for rate-limit decisions."""

from __future__ import annotations

from opentelemetry import metrics, trace

_meter = metrics.get_meter("ums.rate_limit")
_tracer = trace.get_tracer("ums.rate_limit")

_allowed = _meter.create_counter(
    "ums.rate_limit.allowed",
    unit="1",
    description="Requests allowed by the token-bucket limiter",
)
_rejected = _meter.create_counter(
    "ums.rate_limit.rejected",
    unit="1",
    description="Requests rejected by the token-bucket limiter",
)


def record_decision(*, allowed: bool, backend: str) -> None:
    attrs = {"backend": backend}
    if allowed:
        _allowed.add(1, attrs)
    else:
        _rejected.add(1, attrs)


def start_consume_span(*, key: str, backend: str):
    return _tracer.start_as_current_span(
        "rate_limit.consume",
        attributes={"rate_limit.key": key, "rate_limit.backend": backend},
    )
