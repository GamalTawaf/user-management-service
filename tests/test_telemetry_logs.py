"""OTLP logging attachment for Grafana Loki (root + uvicorn loggers)."""

from __future__ import annotations

import logging

from app.telemetry import attach_otlp_logging_handler, parse_log_level
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk.resources import Resource


def test_parse_log_level_valid_and_fallback():
    assert parse_log_level("DEBUG") == logging.DEBUG
    assert parse_log_level(" info ") == logging.INFO
    assert parse_log_level("nope") == logging.INFO


def test_attach_otlp_logging_handler_respects_level_and_is_idempotent():
    provider = LoggerProvider(resource=Resource.create({"service.name": "test-logs"}))
    first = attach_otlp_logging_handler(provider, level=logging.DEBUG)
    second = attach_otlp_logging_handler(provider, level=logging.DEBUG)
    assert isinstance(first, LoggingHandler)
    assert isinstance(second, LoggingHandler)
    assert first.level == logging.DEBUG

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    access = logging.getLogger("uvicorn.access")
    assert access.level == logging.DEBUG
    otel_on_access = [h for h in access.handlers if isinstance(h, LoggingHandler)]
    assert len(otel_on_access) == 1
