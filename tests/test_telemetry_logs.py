"""OTLP logging attachment for Grafana Loki (root + uvicorn loggers)."""

from __future__ import annotations

import logging

from app.telemetry import attach_otlp_logging_handler
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk.resources import Resource


def test_attach_otlp_logging_handler_sets_info_and_is_idempotent():
    provider = LoggerProvider(resource=Resource.create({"service.name": "test-logs"}))
    first = attach_otlp_logging_handler(provider)
    second = attach_otlp_logging_handler(provider)
    assert isinstance(first, LoggingHandler)
    assert isinstance(second, LoggingHandler)

    root = logging.getLogger()
    assert root.level == logging.INFO
    access = logging.getLogger("uvicorn.access")
    assert access.level == logging.INFO
    otel_on_access = [h for h in access.handlers if isinstance(h, LoggingHandler)]
    assert len(otel_on_access) == 1
