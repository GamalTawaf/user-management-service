"""Redact PII/secrets from stdlib logs and OTel ``db.statement`` / ``db.query.text``."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

REDACTED = "[REDACTED]"
_DB_STATEMENT_KEYS = frozenset({"db.statement", "db.query.text"})
# SQL single-quoted literals (including doubled '' escapes).
_SQL_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_BEARER = re.compile(r"(?i)\bBearer\s+\S+")
# Email/display_name are handled via `_EMAIL` / `_SENSITIVE_KEYS` so dict reprs
# like `{'display_name': …, 'ok': 'keep'}` are not swallowed by the field regex.
_FIELD_NAMES = "password|jwt_secret|authorization|access_token|refresh_token"
# Quoted value, or unquoted run until the next known field / end.
_SENSITIVE_FIELD = re.compile(
    rf"(?i)([\"']?(?:{_FIELD_NAMES})[\"']?\s*[:=]\s*)"
    rf"([\"'](?:\\.|[^\"'\\])*[\"']|.+?)"
    rf"(?=,\s*[\"']?(?:{_FIELD_NAMES})|"
    rf"\s+[\"']?(?:{_FIELD_NAMES})[\"']?\s*[:=]|\s*$)"
)


def redact_text(text: str) -> str:
    out = _EMAIL.sub(REDACTED, text)
    out = _JWT.sub(REDACTED, out)
    out = _BEARER.sub(f"Bearer {REDACTED}", out)
    out = _SENSITIVE_FIELD.sub(rf"\1{REDACTED}", out)
    return out


def scrub_db_statement(statement: str) -> str:
    """Mask secrets/PII in SQL text: known field patterns, then all quoted literals."""
    out = redact_text(statement)
    sql_placeholder = f"'{REDACTED}'"
    out = _SQL_STRING_LITERAL.sub(sql_placeholder, out)
    return out


def scrub_span_attributes(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    if not attributes:
        return {}
    out = dict(attributes)
    for key in _DB_STATEMENT_KEYS:
        value = out.get(key)
        if isinstance(value, str):
            out[key] = scrub_db_statement(value)
    return out


def _clone_span_with_scrubbed_attrs(span: ReadableSpan) -> ReadableSpan:
    scrubbed_attrs = scrub_span_attributes(span.attributes)
    context = span.get_span_context()
    return ReadableSpan(
        name=span.name,
        context=context,
        parent=span.parent,
        resource=span.resource,
        attributes=scrubbed_attrs,
        events=span.events,
        links=span.links,
        kind=span.kind,
        status=span.status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class ScrubbingSpanExporter(SpanExporter):
    """Wrap a SpanExporter and scrub ``db.statement`` / ``db.query.text`` before export."""

    def __init__(self, delegate: SpanExporter) -> None:
        self._delegate = delegate

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        scrubbed = [_clone_span_with_scrubbed_attrs(span) for span in spans]
        return self._delegate.export(scrubbed)

    def shutdown(self) -> None:
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._delegate.force_flush(timeout_millis)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: _redact_mapped(key, item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        redacted = [_redact_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(redacted)
        return redacted
    return value


_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "jwt_secret",
        "authorization",
        "email",
        "display_name",
        "access_token",
        "refresh_token",
    }
)


def _redact_mapped(key: Any, value: Any) -> Any:
    key_text = str(key).lower()
    if key_text in _SENSITIVE_KEYS:
        return REDACTED
    return _redact_value(value)


class PiiRedactingFilter(logging.Filter):
    """Mutates the record in place so every handler sees redacted text."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact structured args first, then format, then scrub the rendered line.
        # Avoids mangling templates like ``email=%s`` before %-args apply.
        if record.args:
            record.args = _redact_value(record.args)
        if not isinstance(record.msg, str):
            return True
        try:
            rendered = record.getMessage()
        except Exception:
            record.msg = redact_text(record.msg)
            return True
        record.msg = redact_text(rendered)
        record.args = ()
        return True


_filter_installed = False


def install_pii_log_filter() -> None:
    """Attach once on the root logger (covers child loggers that propagate)."""
    global _filter_installed
    if _filter_installed:
        return
    root = logging.getLogger()
    pii_filter = PiiRedactingFilter()
    root.addFilter(pii_filter)
    _filter_installed = True
