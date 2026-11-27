from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from app.config import settings
from app.db import engine
from app.log_pii import ScrubbingSpanExporter, install_pii_log_filter

_providers_ready = False
_sqlalchemy_instrumented = False
_redis_instrumented = False

# Uvicorn access/error loggers default to propagate=False, so root-only OTEL
# handlers never see request lines that still appear in docker logs.
_OTLP_LOG_TARGETS = (
    "",
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
    "app",
)


def attach_otlp_logging_handler(logger_provider: LoggerProvider) -> LoggingHandler:
    """Install OTEL LoggingHandler on root + uvicorn loggers; force INFO."""
    handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    for name in _OTLP_LOG_TARGETS:
        logger = logging.getLogger(name)
        already = any(isinstance(existing, LoggingHandler) for existing in logger.handlers)
        if not already:
            logger.addHandler(handler)
        if logger.level == logging.NOTSET or logger.level > logging.INFO:
            logger.setLevel(logging.INFO)
    return handler


def configure_telemetry(*, fastapi_app: FastAPI | None = None) -> None:
    global _providers_ready, _sqlalchemy_instrumented, _redis_instrumented

    install_pii_log_filter()

    if not _providers_ready:
        resource = Resource.create({"service.name": settings.otel_service_name})
        tracer_provider = TracerProvider(resource=resource)
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if otlp_endpoint:  # pragma: no cover - exercised in Compose, not unit tests
            span_exporter = ScrubbingSpanExporter(OTLPSpanExporter())
            metric_exporter = OTLPMetricExporter()
            log_exporter = OTLPLogExporter()
            tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
            metric_reader = PeriodicExportingMetricReader(metric_exporter)
            logger_provider = LoggerProvider(resource=resource)
            log_processor = BatchLogRecordProcessor(log_exporter)
            logger_provider.add_log_record_processor(log_processor)
            set_logger_provider(logger_provider)
            attach_otlp_logging_handler(logger_provider)
        else:
            console_spans = ScrubbingSpanExporter(ConsoleSpanExporter())
            tracer_provider.add_span_processor(BatchSpanProcessor(console_spans))
            metric_reader = PeriodicExportingMetricReader(ConsoleMetricExporter())

        trace.set_tracer_provider(tracer_provider)
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)

        LoggingInstrumentor().instrument(set_logging_format=True)
        _providers_ready = True
        logging.getLogger(__name__).info("telemetry providers configured")

    if not _sqlalchemy_instrumented:
        tracer_provider = trace.get_tracer_provider()
        meter_provider = metrics.get_meter_provider()
        SQLAlchemyInstrumentor().instrument(
            engine=engine,
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
            skip_dep_check=True,
        )
        _sqlalchemy_instrumented = True

    if not _redis_instrumented:
        tracer_provider = trace.get_tracer_provider()
        RedisInstrumentor().instrument(tracer_provider=tracer_provider)
        _redis_instrumented = True

    if fastapi_app is not None:
        tracer_provider = trace.get_tracer_provider()
        meter_provider = metrics.get_meter_provider()
        FastAPIInstrumentor.instrument_app(
            fastapi_app,
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
        )


def setup_telemetry(app: FastAPI) -> None:
    configure_telemetry(fastapi_app=app)
