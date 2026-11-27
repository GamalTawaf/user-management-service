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

_claim_conflict_counter = None
_intake_rejection_counter = None
_providers_ready = False
_sqlalchemy_instrumented = False


def configure_telemetry(*, fastapi_app: FastAPI | None = None) -> None:
    """Providers + SQLAlchemy (+ optional FastAPI). Safe to call from API or worker.

    No Redis in this stack. SMTP has no OTel instrumentation package — see
    ``app.outbox.mailer`` for manual ``smtp.send`` spans. Root logger gets a
    PII/PHI redacting filter; span export scrubs ``db.statement`` /
    ``db.query.text``.
    """
    global _claim_conflict_counter, _intake_rejection_counter
    global _providers_ready, _sqlalchemy_instrumented

    install_pii_log_filter()

    if not _providers_ready:
        resource = Resource.create({"service.name": settings.otel_service_name})
        tracer_provider = TracerProvider(resource=resource)
        # ponytail: console when OTLP unset; Compose sets endpoint → grafana/otel-lgtm
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if otlp_endpoint:
            span_exporter = ScrubbingSpanExporter(OTLPSpanExporter())
            metric_exporter = OTLPMetricExporter()
            log_exporter = OTLPLogExporter()
            tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
            metric_reader = PeriodicExportingMetricReader(metric_exporter)
            logger_provider = LoggerProvider(resource=resource)
            log_processor = BatchLogRecordProcessor(log_exporter)
            logger_provider.add_log_record_processor(log_processor)
            set_logger_provider(logger_provider)
            otel_handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
            logging.getLogger().addHandler(otel_handler)
        else:
            console_spans = ScrubbingSpanExporter(ConsoleSpanExporter())
            tracer_provider.add_span_processor(BatchSpanProcessor(console_spans))
            metric_reader = PeriodicExportingMetricReader(ConsoleMetricExporter())

        trace.set_tracer_provider(tracer_provider)
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)

        LoggingInstrumentor().instrument(set_logging_format=True)

        meter = metrics.get_meter("prior-auth-api")
        _claim_conflict_counter = meter.create_counter("claim_conflicts", unit="1")
        _intake_rejection_counter = meter.create_counter("intake_rejections", unit="1")
        _providers_ready = True
        logging.getLogger(__name__).info("telemetry providers configured")

    if not _sqlalchemy_instrumented:
        tracer_provider = trace.get_tracer_provider()
        meter_provider = metrics.get_meter_provider()
        # OTel 0.66b2 still declares sqlalchemy<2.1 but works on 2.1.x; skip the
        # dep check or it instruments nothing. Needs sqlalchemy[asyncio]/greenlet)
        # because the instrumentor always imports sqlalchemy.ext.asyncio.
        SQLAlchemyInstrumentor().instrument(
            engine=engine,
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
            skip_dep_check=True,
        )
        _sqlalchemy_instrumented = True

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


def record_claim_conflict() -> None:
    if _claim_conflict_counter is not None:
        _claim_conflict_counter.add(1)


def record_intake_rejection() -> None:
    if _intake_rejection_counter is not None:
        _intake_rejection_counter.add(1)
